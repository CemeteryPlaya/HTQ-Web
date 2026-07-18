FROM prom/prometheus:v2.53.4
COPY prometheus.yml /etc/prometheus/prometheus.yml
CMD [ "--config.file=/etc/prometheus/prometheus.yml", \
      "--storage.tsdb.path=/prometheus", \
      "--storage.tsdb.retention.time=15d", \
      "--web.console.libraries=/etc/prometheus/console_libraries", \
      "--web.console.templates=/etc/prometheus/consoles", \
      "--web.enable-lifecycle", \
      "--web.external-url=/prometheus" ]
