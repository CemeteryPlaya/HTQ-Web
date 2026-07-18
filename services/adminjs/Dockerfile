FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --production && npm cache clean --force

COPY src/ ./src/

EXPOSE 3300

HEALTHCHECK --interval=10s --timeout=3s --retries=3 --start-period=15s \
  CMD wget -qO- http://127.0.0.1:3300/mongo-admin/api/health || exit 1

CMD ["node", "src/index.js"]
