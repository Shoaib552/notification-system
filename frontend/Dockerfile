FROM node:18-alpine

WORKDIR /app

# Copy dependency catalogs
COPY package.json .

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Expose port
EXPOSE 3000

# Default command starts Vite in dev server mode
CMD ["npm", "run", "dev"]
