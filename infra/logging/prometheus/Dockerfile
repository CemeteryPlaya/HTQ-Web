FROM prom/prometheus:v2.53.4
COPY prometheus.yml /etc/prometheus/prometheus.yml

# Хранение: 30 дней ИЛИ 10 ГБ — что наступит раньше. Потолок по размеру
# важнее срока: без него Prometheus молча съедает диск, а это ровно та
# авария, которую он и должен ловить. Раньше стояло только
# retention.time=15d, то есть ограничения по месту не было вовсе.
#
# expand-external-labels разворачивает ${PROMETHEUS_ENV} в external_labels:
# конфиг вшит в образ на этапе сборки, и подставить стенд иначе негде.
CMD [ "--config.file=/etc/prometheus/prometheus.yml", \
      "--storage.tsdb.path=/prometheus", \
      "--storage.tsdb.retention.time=30d", \
      "--storage.tsdb.retention.size=10GB", \
      "--enable-feature=expand-external-labels", \
      "--web.console.libraries=/etc/prometheus/console_libraries", \
      "--web.console.templates=/etc/prometheus/consoles", \
      "--web.enable-lifecycle", \
      "--web.external-url=/prometheus" ]
