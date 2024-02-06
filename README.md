# Crowdsourced Distributed Domain Validation

## Helpful Commands

### Certbot

- Server needs wildcard cert!
- Easiest is to add DNS TXT record in registrar dashboard.
- Run anywhere: `sudo certbot certonly --manual --preferred-challenges dns -d example.com -d *.example.com`.
- Copy created `fullchain.pem` and `privkey.pem` files to `nginx/server.crt` and `nginx/server.key` before building container image.


### Docker

- Build project with `docker build -t addv .` from project root directory ([Troubleshooting](#docker-build)).
- Export image with `docker save -o addv-img.tar addv`.
- Upload to server with `scp addv-img.tar user@example.com:/home/user`
- Import image on server with `docker load -i addv-img.tar`
- Run image with `docker run -d -p 80:80 -p 443:443 -v /home/user/addvlogs:/app/logs -e MEASUREMENT_MODE=1 -e SERVER_NAME example.com --shm-size 64MiB --name addv addv`
- Note: default for `shm-size` is 64MiB; set appropriately based on shared memory settings in `app.py`


### Troubleshooting
#### Docker Build
- if having "temporary failure resolving ...", try adding `--network=host` option
- if this doesn't work try disconnecting VPN first


### Adnets

- Default key is "RANDOMKEY", configured in `nginx/server.conf`
- Adnet target URL should be `https://example.com/addv/RANDOMKEY/val/join`


### API

- Queue a domain with `https://example.com/addv/RANDOMKEY/queue?domain=validate.me`
