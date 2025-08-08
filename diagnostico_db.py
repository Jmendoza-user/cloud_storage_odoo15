import os
import psycopg2
from datetime import datetime

# Configuración de conexión
conn = psycopg2.connect(
    host="10.10.6.222",
    port=5432,
    database="odooenvironment",
    user="odoo15",
    password="Odoo2023*"
)
cursor = conn.cursor()

# Ruta del filestore y log
filestore_path = os.path.expanduser("~/.local/share/Odoo/filestore/odooenvironment")
log_file = "filestore_check.log"

def write_log(lines):
    with open(log_file, "a") as f:
        for line in lines:
            f.write(line + "\n")

# Marcar inicio
write_log([
    "",
    f"--- Verificación del filestore - {datetime.now()} ---"
])

# Archivos desde la base de datos
cursor.execute("SELECT store_fname FROM ir_attachment WHERE store_fname IS NOT NULL")
db_files = set(row[0] for row in cursor.fetchall())

# Archivos físicos reales
fs_files = set()
for root, dirs, files in os.walk(filestore_path):
    for name in files:
        rel_path = os.path.relpath(os.path.join(root, name), filestore_path)
        fs_files.add(rel_path)

# Comparar
huérfanos_db = db_files - fs_files  # En la BD pero no en disco
basura_fs = fs_files - db_files     # En disco pero no en BD

# Reportar
lines = []
lines.append(f"📂 Archivos huérfanos en base de datos: {len(huérfanos_db)}")
for f in sorted(huérfanos_db):
    lines.append(f"  - {f}")

lines.append(f"\n🗑️ Archivos basura en disco: {len(basura_fs)}")
for f in sorted(basura_fs):
    lines.append(f"  - {f}")

write_log(lines)

print("✅ Revisión completada. Incidencias guardadas en 'filestore_check.log'")

# Cerrar conexión
cursor.close()
conn.close()
