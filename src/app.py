#!/usr/bin/env python3
import json
import os
import random
import re
import string
from datetime import datetime
from hashlib import sha256
from ipaddress import IPv4Network
from itertools import islice
from multiprocessing.pool import ThreadPool
from time import time
from typing import Set, Tuple, Any, List

import dns.resolver
from UltraDict import UltraDict
from dns.exception import DNSException
from flask import Flask, request, render_template
from flask_cors import CORS
from werkzeug.exceptions import BadRequest

from utils import get_shm_size

SIG_KEY = "".join(random.choices(string.ascii_letters + string.digits, k=50))

BATCH_SIZE = 20
POOL_SIZE = 120
PREFIX_LEN = 16
AUTH_TIMEOUT = 120
MIN_ANSWERS = 7
N_REPORT_SUBS = 10  # should be at least ceil(BATCH_SIZE / 6)
MIN_CONSENSUS = 5   # account for up to 2 false negatives
CHALLENGE_LEN = 43  # same as Let's Encrypt
DNS_ATTEMPTS = 3

MEASUREMENT_MODE = bool(os.getenv("MEASUREMENT_MODE")) or False
SERVER_NAME = os.getenv("SERVER_NAME") or "localhost"
REPORTING_SUBDOMAINS = ["localhost"] * BATCH_SIZE if SERVER_NAME == "localhost" else [f"rep{i % N_REPORT_SUBS}.{SERVER_NAME}" for i in range(BATCH_SIZE)]

PID = 0

app = Flask(__name__)
CORS(app)
resolver = dns.resolver.Resolver()
resolver.nameservers = ["8.8.8.8", "8.8.4.4", "9.9.9.9", "1.1.1.1", "1.0.0.1"]

shm_size = get_shm_size() or 64 * 1024**2
queue = UltraDict({}, name="queue", buffer_size=int(0.2 * shm_size), auto_unlink=True)


@app.route("/addv/<key>", methods=["GET"])
def base(key: str):
    return "ADDV Server\n"


@app.route("/opt-out", methods=["GET"])
def opt_out():
    log("OPTOUT", ip=request.headers.get("X-Real-IP"))
    return "OK\n"


@app.route("/addv/<key>/queue-batch", methods=["POST"])
def queue_batch(key: str):
    domains = set(request.get_json()["domains"])
    return "".join(queue_validation(domain) for domain in domains)


@app.route("/addv/<key>/queue", methods=["GET"])
def queue_domain(key: str):
    domain = request.args.get("domain", "").lower()
    return queue_validation(domain)


def queue_validation(domain: str):
    if re.match("[a-z0-9.-]+", domain):
        if not queue.get(domain):
            data = {"time": datetime.now().isoformat(), "answers": {}, "challenge": gen_challenge(), "ips": ips_of(domain)}
            queue[domain] = data
            log("QUEUED", domain=domain, challenge=data["challenge"], ips=data["ips"])

            return "OK\n"
        return "ALREADY QUEUED\n"
    return "ERROR\n"


@app.route("/addv/<key>/val/join", methods=["GET"])
def validator_join(key: str):
    client_ip = request.headers.get("X-Real-IP")

    challenges = select_domains(client_ip)
    auth_time = str(int(time()))
    challenges = [(domain, challenge, keyed_hash(domain, client_ip, auth_time), REPORTING_SUBDOMAINS[i]) for i, (domain, challenge) in enumerate(challenges)]
    log("JOINED", ip=client_ip, key=key, assigned=[domain for domain, _, _, _ in challenges])

    return render_template("validator.html", key=key, auth_time=auth_time, challenges=challenges)


@app.route("/addv/<key>/val/answer", methods=["GET"])
def validator_answer(key: str):
    try:
        data = request.args
        try:
            domain = data["domain"]
            client_ip = request.headers.get("X-Real-IP")

            if keyed_hash(domain, client_ip, data["authtime"]) == data["sig"] and time() < int(data["authtime"]) + AUTH_TIMEOUT:
                ip_net = subnet_of(client_ip)
                if ip_net not in queue[domain]["answers"].keys():

                    answer = {"answer": data.get("answer", "error"), "time": datetime.fromtimestamp(float(data["time"]) / 1000).isoformat()}
                    entry = queue[domain]
                    entry["answers"][ip_net] = answer
                    log("ANSWERED", ip=client_ip, key=key, domain=domain, answer=data.get("answer", "error"))

                    if len(entry["answers"]) >= MIN_ANSWERS:
                        del queue[domain]
                        event = "VALIDATED" if sum(answer.get("answer") == "success" for answer in entry["answers"].values()) >= MIN_CONSENSUS else "INVALIDATED"
                        log(event, domain=domain, ips=entry["ips"], challenge=entry["challenge"], answers=entry["answers"])
                    else:
                        queue[domain] = entry

                    return "OK\n"
        except (KeyError, ValueError):
            pass
    except BadRequest:
        pass
    return "ERROR\n"


def select_domains(ip: str) -> Set[Tuple[str, str]]:
    ip_net = subnet_of(ip)
    selection = set()
    selected_domains = set()
    pool = set(islice(queue.keys(), POOL_SIZE))

    while len(selection) < min(BATCH_SIZE, len(pool)):
        new_domains = random.sample(list(pool - selected_domains), k=min(BATCH_SIZE - len(selection), len(pool)))
        for domain in new_domains:
            if ip_net not in queue[domain]["answers"].keys():
                selection.add((domain, queue[domain]["challenge"]))
        selected_domains = selected_domains.union(new_domains)

    return selection


def subnet_of(ip: str) -> str:
    return str(IPv4Network(f"{ip}/{PREFIX_LEN}", strict=False))


def ips_of(domain: str) -> List[str]:
    for _ in range(DNS_ATTEMPTS):
        try:
            return [str(ip) for ip in resolver.resolve(domain, "A").rrset]
        except DNSException:
            pass
    return []


def gen_challenge() -> str:
    if MEASUREMENT_MODE:
        return "favicon.ico"
    return "".join(random.choices(string.ascii_letters + string.digits, k=CHALLENGE_LEN)) + "/pixel.png"


def keyed_hash(*args: str) -> str:
    return sha256("|".join(args + (SIG_KEY,)).encode()).hexdigest()


def log(event: str, **data: Any):
    global PID
    if not PID:
        PID = os.getpid()

    d = {"event": event, "time": datetime.now().isoformat()}
    d.update(data)
    with open(f"/app/logs/app-{PID}.jsonl", "a") as f:
        f.write(json.dumps(d) + "\n")


def preload_queue(filename: str):
    def write_to_queue(line: str):
        domain = line.strip()
        data = {"time": datetime.now().isoformat(), "answers": {}, "challenge": gen_challenge(), "ips": ips_of(domain)}
        queue[domain] = data
        log("QUEUED", domain=domain, challenge=data["challenge"], ips=data["ips"])

    try:
        with open(filename) as f:
            with ThreadPool() as pool:
                pool.map(write_to_queue, f, chunksize=100)
        global PID
        PID = 0
    except FileNotFoundError:
        pass


preload_queue("/app/logs/queue-preload.lst")

if __name__ == '__main__':
    app.run()
