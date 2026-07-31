FROM node:20-alpine AS build
WORKDIR /app
COPY apps/evaluation_ui/package*.json ./
RUN npm install
COPY apps/evaluation_ui/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
