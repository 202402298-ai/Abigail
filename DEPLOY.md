# Despliegue a producción — Seguimiento ITSM

Guía para pasar el sistema de tu entorno local (SQLite, `runserver`) a un
servidor Windows en producción (Postgres, Waitress como servicio de Windows).

## 1. Instalar PostgreSQL en el servidor

1. Descarga el instalador desde https://www.postgresql.org/download/windows/
2. Durante la instalación, define una contraseña para el usuario `postgres` (guárdala).
3. Con `psql` o pgAdmin, crea la base y el usuario de la app:

```sql
CREATE DATABASE seguimiento_itsm;
CREATE USER seguimiento_itsm WITH PASSWORD 'una-password-fuerte-aqui';
GRANT ALL PRIVILEGES ON DATABASE seguimiento_itsm TO seguimiento_itsm;
ALTER DATABASE seguimiento_itsm OWNER TO seguimiento_itsm;
```

## 2. Copiar el proyecto al servidor

Copia la carpeta del proyecto (o clónala con git si ya la subiste a un
repositorio) a algo como `C:\apps\seguimiento-itsm`.

## 3. Crear el entorno virtual e instalar dependencias

```powershell
cd C:\apps\seguimiento-itsm
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4. Configurar el archivo `.env`

Copia `.env.example` a `.env` y llena los valores reales:

```powershell
copy .env.example .env
```

- `DJANGO_SECRET_KEY`: genera una nueva con
  `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
  (nunca reuses la de desarrollo)
- `DJANGO_DEBUG=False`
- `DJANGO_ALLOWED_HOSTS`: el dominio o IP real por donde se va a acceder
- `DATABASE_URL=postgres://seguimiento_itsm:la-password@localhost:5432/seguimiento_itsm`
- `DJANGO_SECURE_SSL_REDIRECT`: déjalo en `False` la primera vez que pruebes
  (todavía sin HTTPS) y cámbialo a `True` en cuanto tengas el certificado (paso 8)

## 5. Migrar los datos reales (no partir de una BD vacía)

Como ya tienes notas de seguimiento escritas a mano y varias importaciones en
el historial, conviene llevar los datos reales de SQLite a Postgres en vez de
empezar de cero. Desde tu entorno de **desarrollo** (con SQLite, sin tocar el
`.env` todavía):

```powershell
$env:PYTHONUTF8 = "1"   # importante: sin esto, dumpdata falla en Windows con datos que tienen tildes/ñ
python manage.py dumpdata --natural-foreign --natural-primary `
  --exclude contenttypes --exclude auth.permission --exclude admin.logentry --exclude sessions.session `
  --output datadump.json
```

> Probé este comando contra la base real (2,668 tickets): sin `PYTHONUTF8=1`
> falla a la mitad con un error de codificación por los acentos; con esa
> variable puesta, genera el archivo completo sin problema.

Copia `datadump.json` al servidor de producción. Ahí, ya con el `.env`
apuntando a Postgres:

```powershell
python manage.py migrate
$env:PYTHONUTF8 = "1"
python manage.py loaddata datadump.json
```

Verifiqué que este `dumpdata` + `loaddata` restaura todo correctamente
(tickets, notas de seguimiento, historial de importaciones, usuarios, y los
acentos/ñ se conservan bien) restaurándolo en una base de prueba antes de
escribir esta guía.

(Si prefieres empezar limpio en vez de migrar el historial, basta con
`python manage.py migrate` y luego volver a subir el último XML desde
"Subir XML" — el sistema reconstruye todo excepto las notas de seguimiento
manuales, que se perderían.)

## 6. Preparar los estáticos y probar

```powershell
python manage.py collectstatic --noinput
python manage.py createsuperuser   # si no migraste los usuarios existentes
waitress-serve --host=0.0.0.0 --port=8000 seguimiento_itsm.wsgi:application
```

Entra a `http://<ip-del-servidor>:8000/` y confirma que todo carga bien
(dashboard, tickets, subir XML) antes de seguir.

## 7. Instalar como servicio de Windows (con NSSM)

Para que la app arranque sola con el servidor y siga corriendo en segundo
plano:

1. Descarga NSSM: https://nssm.cc/download
2. Instala el servicio:

```powershell
nssm install SeguimientoITSM "C:\apps\seguimiento-itsm\venv\Scripts\waitress-serve.exe" "--host=0.0.0.0 --port=8000 seguimiento_itsm.wsgi:application"
nssm set SeguimientoITSM AppDirectory "C:\apps\seguimiento-itsm"
nssm start SeguimientoITSM
```

Con esto, Windows lo reinicia solo si el servidor se reinicia o el proceso
se cae.

## 8. HTTPS

Waitress no maneja HTTPS directamente; necesitas algo delante que sí lo
haga. Dos opciones:

- **Caddy** (más simple): se pone delante de Waitress y consigue el
  certificado de Let's Encrypt automáticamente. Un `Caddyfile` mínimo:
  ```
  seguimiento-itsm.tudominio.com {
      reverse_proxy localhost:8000
  }
  ```
- **IIS**: si el servidor ya usa IIS, se configura como reverse proxy hacia
  `localhost:8000` con el módulo Application Request Routing (ARR) + URL
  Rewrite, y el certificado se instala en el sitio de IIS como cualquier
  otro sitio.

Una vez que HTTPS esté funcionando, cambia `DJANGO_SECURE_SSL_REDIRECT=True`
en el `.env` y reinicia el servicio (`nssm restart SeguimientoITSM`).

## Actualizaciones futuras

Cuando cambies código y quieras actualizar producción:

```powershell
git pull   # o copiar los archivos nuevos
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
nssm restart SeguimientoITSM
```
