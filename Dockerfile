FROM python:3.12-slim

WORKDIR /app

# Pillow y pillow-heif traen ruedas precompiladas para linux: no hace falta compilar nada.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El contenedor no publica puertos: solo se llega desde la red de Docker, o sea desde nginx.
EXPOSE 8020

# --proxy-headers para que la IP real llegue desde nginx; sin eso el límite de intentos
# de login contaría todo como una sola IP y bloquearía a todo el mundo junto.
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8020", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
