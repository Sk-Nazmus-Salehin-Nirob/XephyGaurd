FROM mitmproxy/mitmproxy:12.3.1@sha256:2711066c855659b5af8b1dbb84494ed3eff69b42ece439c60b4fe09a2db829d4
# Dedicated uid/gid 1500 (owner of the CA bundle on the host, see install.sh).
RUN groupmod -o -g 1500 mitmproxy && usermod -o -u 1500 -g 1500 mitmproxy && chown -R 1500:1500 /home/mitmproxy
COPY proxy/xg_netpolicy /opt/xephyguard/proxy/xg_netpolicy
COPY proxy/addons /opt/xephyguard/proxy/addons
COPY ccc-deploy/docker/proxy-entrypoint.sh /opt/xephyguard/proxy-entrypoint.sh
RUN chmod +x /opt/xephyguard/proxy-entrypoint.sh
# The proxy's own interception CA (key + cert, bin/xg-interception-ca.sh; never the lab root key, I-CCC-3)
# is mounted at the default confdir /home/mitmproxy/.mitmproxy as mitmproxy-ca.pem (0600, owned by uid 1500).
# The image entrypoint then runs mitmproxy as that uid.
CMD ["/opt/xephyguard/proxy-entrypoint.sh"]
