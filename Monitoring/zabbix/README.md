# mumble-scripts - Zabbix

Murmur server monitoring setup for [zabbix](https://zabbix.com)

Testet on:

-   Debian
    -   11 (Bullseye)

## License

AGPL-3.0-or-later

## Setup

### Installation

```bash
# Install packages
apt install curl python3-zeroc-ice zeroc-ice-slice

# Deploy script
curl \
  -o /usr/local/bin/murmur-munin \
  'https://raw.githubusercontent.com/mumble-voip/mumble-scripts/master/Monitoring/munin-murmur.py'
sed -i '/secureme/${secureme?}/' /usr/local/bin/murmur-munin
chmod +x /usr/local/bin/murmur-munin

# Deploy zabbix userparameter
curl \
  -o "/etc/zabbix/zabbix_agent2.d/userparameter_murmur.conf" \
  'https://raw.githubusercontent.com/mumble-voip/mumble-scripts/master/Monitoring/zabbix/userparameter_murmur.conf'
systemctl restart zabbix-agent2.service
```

### Template

Import the zabbix Tempalte:

*   [zabbix_6.0_template_murmur.yaml](/mumble-voip/mumble-scripts/Monitoring/zabbix/zabbix_6.0_template_murmur.yaml)
