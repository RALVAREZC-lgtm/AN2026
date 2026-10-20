import sqlite3
import pandas as pd
import hashlib
import json
from datetime import datetime

# ==========================================
# 1. BASE DE DATOS Y CARGA DEL PADRÓN ELECTORAL
# ==========================================
class ElectoralDatabase:
    def __init__(self, db_name="ahora_nacion_electoral.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Tabla de Locales de Votación
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS locales_votacion (
            codigo_lv INTEGER PRIMARY KEY,
            odpe TEXT,
            ubigeo INTEGER,
            departamento TEXT,
            provincia TEXT,
            distrito TEXT,
            nombre_local TEXT,
            direccion_local TEXT
        )
        ''')

        # Tabla de Mesas de Sufragio
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS mesas_sufragio (
            mesa_sufragio INTEGER PRIMARY KEY,
            codigo_lv INTEGER,
            aula INTEGER,
            piso INTEGER,
            pabellon INTEGER,
            electores INTEGER,
            electores_discapacidad INTEGER,
            FOREIGN KEY (codigo_lv) REFERENCES locales_votacion(codigo_lv)
        )
        ''')

        # Tabla de Usuarios / Personeros / Coordinadores
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            dni TEXT PRIMARY KEY,
            nombre TEXT,
            telefono TEXT,
            rol TEXT, -- 'PERSONERO', 'COORDINADOR_LOCAL', 'COORDINADOR_DISTRITAL', 'COMANDO'
            password_hash TEXT,
            estado TEXT DEFAULT 'ACTIVO'
        )
        ''')

        # Tabla de Asignaciones
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS asignaciones_personero (
            id_asignacion INTEGER PRIMARY KEY AUTOINCREMENT,
            dni_personero TEXT,
            mesa_sufragio INTEGER,
            checkin_status INTEGER DEFAULT 0,
            checkin_timestamp TEXT,
            latitud REAL,
            longitud REAL,
            FOREIGN KEY (dni_personero) REFERENCES usuarios(dni),
            FOREIGN KEY (mesa_sufragio) REFERENCES mesas_sufragio(mesa_sufragio)
        )
        ''')

        # Tabla de Actas de Segunda Vuelta
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS actas_segunda_vuelta (
            mesa_sufragio INTEGER PRIMARY KEY,
            dni_personero TEXT,
            votos_ahora_nacion INTEGER,
            votos_contendiente INTEGER,
            votos_blancos INTEGER,
            votos_nulos INTEGER,
            votos_impugnados INTEGER,
            total_emitidos INTEGER,
            foto_acta_url TEXT,
            estado_acta TEXT, -- 'VALIDADA', 'OBSERVADA'
            fecha_registro TEXT,
            FOREIGN KEY (mesa_sufragio) REFERENCES mesas_sufragio(mesa_sufragio)
        )
        ''')

        # Tabla de Alertas / Incidencias
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS incidencias_legales (
            id_incidencia INTEGER PRIMARY KEY AUTOINCREMENT,
            mesa_sufragio INTEGER,
            dni_reporta TEXT,
            tipo_incidencia TEXT,
            descripcion TEXT,
            prioridad TEXT, -- 'ALTA', 'MEDIA', 'BAJA'
            fecha_hora TEXT
        )
        ''')

        self.conn.commit()

    def cargar_excel_maestro(self, excel_path="Maestro_EMR2026.xlsx"):
        df = pd.read_excel(excel_path, sheet_name='TacnaEMR2026')
        cursor = self.conn.cursor()

        # Extraer locales únicos
        locales = df[['CÓDIGO DE LV', 'ODPE', 'UBIGEO', 'DEPARTAMENTO', 'PROVINCIA', 
                      'DISTRITO', 'NOMBRE DE LOCAL DE VOTACIÓN', 'DIRECCION DEL LOCAL DE VOTACIÓN']].drop_duplicates()
        
        for _, r in locales.iterrows():
            cursor.execute('''
            INSERT OR REPLACE INTO locales_votacion VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (r['CÓDIGO DE LV'], r['ODPE'], r['UBIGEO'], r['DEPARTAMENTO'], 
                  r['PROVINCIA'], r['DISTRITO'], r['NOMBRE DE LOCAL DE VOTACIÓN'], r['DIRECCION DEL LOCAL DE VOTACIÓN']))

        # Extraer mesas de sufragio
        mesas = df[['MESA DE SUFRAGIO', 'CÓDIGO DE LV', 'AULA', 'PISO', 'PABELLÓN', 'ELECTORES', 'ELECTORES CON DISCAPACIDAD']]
        for _, r in mesas.iterrows():
            cursor.execute('''
            INSERT OR REPLACE INTO mesas_sufragio VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (r['MESA DE SUFRAGIO'], r['CÓDIGO DE LV'], r['AULA'], r['PISO'], r['PABELLÓN'], r['ELECTORES'], r['ELECTORES CON DISCAPACIDAD']))

        self.conn.commit()
        print(f"Padrón Maestro cargado correctamente: {len(locales)} locales y {len(mesas)} mesas.")


# ==========================================
# 2. MOTOR DE LOGICA DE NEGOCIO Y SERVICIOS
# ==========================================
class ServicioElectoral:
    def __init__(self, db: ElectoralDatabase):
        self.db = db

    def hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def registrar_usuario(self, dni, nombre, telefono, rol, password):
        cursor = self.db.conn.cursor()
        pwd_hash = self.hash_password(password)
        cursor.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?, ?, 'ACTIVO')",
                       (dni, nombre, telefono, rol, pwd_hash))
        self.db.conn.commit()
        return {"status": "SUCCESS", "message": f"Usuario {nombre} registrado como {rol}."}

    def autenticar_usuario(self, dni, password):
        cursor = self.db.conn.cursor()
        pwd_hash = self.hash_password(password)
        cursor.execute("SELECT dni, nombre, rol FROM usuarios WHERE dni = ? AND password_hash = ?", (dni, pwd_hash))
        user = cursor.fetchone()
        if user:
            return {"autenticado": True, "user": {"dni": user[0], "nombre": user[1], "rol": user[2]}}
        return {"autenticado": False, "message": "Credenciales inválidas."}

    def consultar_mesa(self, mesa_sufragio):
        """Módulo de consulta de mesas de votación"""
        cursor = self.db.conn.cursor()
        query = '''
        SELECT m.mesa_sufragio, m.aula, m.piso, m.pabellon, m.electores, m.electores_discapacidad,
               l.nombre_local, l.direccion_local, l.distrito, l.provincia, l.departamento
        FROM mesas_sufragio m
        JOIN locales_votacion l ON m.codigo_lv = l.codigo_lv
        WHERE m.mesa_sufragio = ?
        '''
        cursor.execute(query, (mesa_sufragio,))
        res = cursor.fetchone()
        if res:
            return {
                "mesa": res[0], "aula": res[1], "piso": res[2], "pabellon": res[3],
                "electores": res[4], "discapacidad": res[5],
                "local": res[6], "direccion": res[7], "distrito": res[8],
                "provincia": res[9], "departamento": res[10]
            }
        return None

    def asignar_personero_mesa(self, dni_personero, mesa_sufragio):
        """Módulo de asignación de personeros"""
        cursor = self.db.conn.cursor()
        cursor.execute("INSERT INTO asignaciones_personero (dni_personero, mesa_sufragio) VALUES (?, ?)",
                       (dni_personero, mesa_sufragio))
        self.db.conn.commit()
        return {"status": "SUCCESS", "message": f"Personero DNI {dni_personero} asignado a Mesa {mesa_sufragio}."}

    def checkin_personero(self, dni_personero, latitud, longitud):
        """Registro de asistencia por GPS el día de la elección"""
        cursor = self.db.conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
        UPDATE asignaciones_personero 
        SET checkin_status = 1, checkin_timestamp = ?, latitud = ?, longitud = ?
        WHERE dni_personero = ?
        ''', (now, latitud, longitud, dni_personero))
        self.db.conn.commit()
        return {"status": "CHECKIN_OK", "timestamp": now}

    def registrar_acta_segunda_vuelta(self, dni_personero, mesa_sufragio, v_ahora_nacion, v_contendiente, v_blancos, v_nulos, v_impugnados, foto_url):
        """Módulo de conteo rápido y validación de actas"""
        cursor = self.db.conn.cursor()
        
        # Verificar capacidad de la mesa
        cursor.execute("SELECT electores FROM mesas_sufragio WHERE mesa_sufragio = ?", (mesa_sufragio,))
        mesa_info = cursor.fetchone()
        if not mesa_info:
            return {"status": "ERROR", "message": "Mesa no existente."}
        
        max_electores = mesa_info[0]
        total_calculado = v_ahora_nacion + v_contendiente + v_blancos + v_nulos + v_impugnados

        # Regla Ágil de Validación
        estado = "VALIDADA"
        if total_calculado > max_electores:
            estado = "OBSERVADA_EXCESO_VOTOS"
        elif total_calculado == 0:
            estado = "OBSERVADA_SIN_VOTOS"

        now = datetime.now().isoformat()
        cursor.execute('''
        INSERT OR REPLACE INTO actas_segunda_vuelta VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (mesa_sufragio, dni_personero, v_ahora_nacion, v_contendiente, v_blancos, v_nulos, v_impugnados, total_calculado, foto_url, estado, now))
        
        self.db.conn.commit()
        return {
            "status": "REGISTRADO",
            "estado_acta": estado,
            "total_emitidos": total_calculado,
            "max_electores_mesa": max_electores
        }

    def registrar_incidencia(self, mesa_sufragio, dni_reporta, tipo, descripcion, prioridad="ALTA"):
        cursor = self.db.conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
        INSERT INTO incidencias_legales (mesa_sufragio, dni_reporta, tipo_incidencia, descripcion, prioridad, fecha_hora)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (mesa_sufragio, dni_reporta, tipo, descripcion, prioridad, now))
        self.db.conn.commit()
        return {"status": "INCIDENCIA_REGISTRADA", "id": cursor.lastrowid}

    def obtener_resumen_computo_regional(self):
        """Dashboard de Segunda Vuelta"""
        cursor = self.db.conn.cursor()
        cursor.execute('''
        SELECT 
            COUNT(mesa_sufragio) as actas_procesadas,
            SUM(votos_ahora_nacion) as total_ahora_nacion,
            SUM(votos_contendiente) as total_contendiente,
            SUM(votos_blancos) as total_blancos,
            SUM(votos_nulos) as total_nulos,
            SUM(total_emitidos) as total_votantes
        FROM actas_segunda_vuelta
        WHERE estado_acta = 'VALIDADA'
        ''')
        res = cursor.fetchone()
        
        cursor.execute("SELECT COUNT(*) FROM mesas_sufragio")
        total_mesas = cursor.fetchone()[0]

        return {
            "total_mesas_region": total_mesas,
            "actas_procesadas": res[0] if res[0] else 0,
            "porcentaje_escrutado": round(((res[0] or 0) / total_mesas) * 100, 2),
            "resultados": {
                "AHORA_NACION": res[1] or 0,
                "CONTENDIENTE": res[2] or 0,
                "BLANCOS": res[3] or 0,
                "NULOS": res[4] or 0,
                "TOTAL_EMITIDOS": res[5] or 0
            }
        }


# ==========================================
# 3. EJECUCIÓN Y DEMOSTRACIÓN DEL SISTEMA
# ==========================================
if __name__ == "__main__":
    # Inicializar Base de Datos
    db = ElectoralDatabase()
    
    # Cargar datos reales desde el archivo maestro Excel
    db.cargar_excel_maestro("Maestro_EMR2026.xlsx")
    
    app = ServicioElectoral(db)

    print("\n--- 1. AUTENTICACIÓN Y SEGURIDAD ---")
    app.registrar_usuario("45879632", "Carlos Mendoza", "952123456", "PERSONERO", "ClaveSegura2026")
    login = app.autenticar_usuario("45879632", "ClaveSegura2026")
    print("Login Result:", login)

    print("\n--- 2. CONSULTA DE MESA DE VOTACIÓN ---")
    # Consulta de la Mesa N° 78981 (Presente en la BD)
    info_mesa = app.consultar_mesa(78981)
    print("Ficha de Mesa:", json.dumps(info_mesa, indent=2, ensure_ascii=False))

    print("\n--- 3. ASIGNACIÓN Y CHECK-IN GPS ---")
    app.asignar_personero_mesa("45879632", 78981)
    checkin = app.checkin_personero("45879632", latitud=-18.0135, longitud=-70.2519)
    print("Check-in Status:", checkin)

    print("\n--- 4. DIGITACIÓN Y VALIDACIÓN DE ACTA (SEGUNDA VUELTA) ---")
    # Mesa 78981 tiene 300 electores. Registramos votos:
    acta_res = app.registrar_acta_segunda_vuelta(
        dni_personero="45879632",
        mesa_sufragio=78981,
        v_ahora_nacion=165,
        v_contendiente=110,
        v_blancos=8,
        v_nulos=12,
        v_impugnados=0,
        foto_url="https://storage.ahoranacion.pe/actas/78981.jpg"
    )
    print("Resultado de Carga de Acta:", acta_res)

    print("\n--- 5. REGISTRO DE INCIDENCIA LEGAL ---")
    incidencia = app.registrar_incidencia(
        mesa_sufragio=78981,
        dni_reporta="45879632",
        tipo="PROPAGANDA_PROHIBIDA",
        descripcion="Personero rival distribuyendo volantes dentro del local.",
        prioridad="ALTA"
    )
    print("Registro de Alerta:", incidencia)

    print("\n--- 6. DASHBOARD CÓMPUTO REGIONAL EN TIEMPO REAL ---")
    computo = app.obtener_resumen_computo_regional()
    print("Avance de Cómputo:", json.dumps(computo, indent=2, ensure_ascii=False))