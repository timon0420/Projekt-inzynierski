FROM node:22-alpine AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG VITE_API_BASE_URL=https://websocket-inzynierka.onrender.com
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist/ /usr/share/nginx/html/

ENV PORT=10000

EXPOSE 10000

CMD ["nginx", "-g", "daemon off;"]
