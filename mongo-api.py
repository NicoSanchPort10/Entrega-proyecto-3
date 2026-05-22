from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient, DESCENDING, ASCENDING
from bson import ObjectId
from datetime import datetime
import os

app = FastAPI(title="Dann-Alpes Reviews API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── Conexión ──────────────────────────────────────────────────────────────────
# Local / servidor Uniandes:
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://ISIS2304A20202610:Fp6BX3fzAN7X@157.253.236.88:8087")
MONGO_DB  = os.environ.get("MONGO_DB",  "ISIS2304A20202610")

client = MongoClient(MONGO_URI)
db     = client[MONGO_DB]

resenas        = db["resenas"]
votos_utilidad = db["votos_utilidad"]

# ── Helper: convierte ObjectId a string para poder serializar ─────────────────
def serial(doc):
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc

# =============================================================================
# ENDPOINTS DEL TALLER ANTERIOR (Parranderos) – se mantienen intactos
# =============================================================================

@app.get("/")
def inicio():
    return {"estado": "API Dann-Alpes funcionando correctamente"}

@app.get("/bares/{bar_id}/comentarios")
def get_comentarios(bar_id: int):
    comentarios = list(db["comentarios_bares"].find({"bar_id": bar_id}, {"_id": 0}))
    return comentarios

@app.post("/bares/{bar_id}/comentarios")
def post_comentario(bar_id: int, datos: dict):
    datos["bar_id"] = bar_id
    datos["fecha"]  = datetime.now().isoformat()
    db["comentarios_bares"].insert_one(datos)
    return {"mensaje": "Comentario guardado"}

@app.get("/bares/{bar_id}/eventos")
def get_eventos(bar_id: int):
    eventos = list(db["eventos"].find({"bar_id": bar_id}, {"_id": 0}))
    return eventos

@app.post("/bares/{bar_id}/eventos")
def post_evento(bar_id: int, evento: dict):
    evento["bar_id"]         = bar_id
    evento["fecha_creacion"] = datetime.now().isoformat()
    db["eventos"].insert_one(evento)
    return {"mensaje": "Evento agregado"}


# =============================================================================
# MÓDULO DE RESEÑAS DANN-ALPES
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# RF1 – Crear reseña
# POST /hoteles/{hotel_id}/resenas
# Body: { "id_cliente": int, "id_reserva": int, "calificacion": int, "texto": str }
# Regla: la reserva no puede tener ya una reseña (id_reserva único)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/hoteles/{hotel_id}/resenas")
def crear_resena(hotel_id: int, datos: dict):
    # Verificar que la reserva no tenga ya una reseña
    if resenas.find_one({"id_reserva": datos.get("id_reserva")}):
        raise HTTPException(status_code=400, detail="Ya existe una reseña para esta reserva.")

    if not datos.get("calificacion") or not (1 <= int(datos["calificacion"]) <= 5):
        raise HTTPException(status_code=400, detail="La calificación debe estar entre 1 y 5.")

    if not datos.get("texto") or len(datos["texto"].strip()) < 10:
        raise HTTPException(status_code=400, detail="El texto debe tener al menos 10 caracteres.")

    doc = {
        "id_hotel":       hotel_id,
        "id_cliente":     int(datos["id_cliente"]),
        "id_reserva":     int(datos["id_reserva"]),
        "calificacion":   int(datos["calificacion"]),
        "texto":          datos["texto"].strip(),
        "estado":         "publicada",
        "fecha_creacion": datetime.now(),
        "votos_utilidad": 0,
        "destacada":      False
    }
    resultado = resenas.insert_one(doc)
    return {"mensaje": "Reseña creada", "id": str(resultado.inserted_id)}


# ─────────────────────────────────────────────────────────────────────────────
# RF2 – Editar reseña
# PUT /resenas/{resena_id}
# Body: { "calificacion": int, "texto": str }
# ─────────────────────────────────────────────────────────────────────────────
@app.put("/resenas/{resena_id}")
def editar_resena(resena_id: str, datos: dict):
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada.")
    if resena["estado"] == "eliminada":
        raise HTTPException(status_code=400, detail="No se puede editar una reseña eliminada.")

    cambios = {"fecha_modificacion": datetime.now()}

    if "calificacion" in datos:
        if not (1 <= int(datos["calificacion"]) <= 5):
            raise HTTPException(status_code=400, detail="La calificación debe estar entre 1 y 5.")
        cambios["calificacion"] = int(datos["calificacion"])

    if "texto" in datos:
        if len(datos["texto"].strip()) < 10:
            raise HTTPException(status_code=400, detail="El texto debe tener al menos 10 caracteres.")
        cambios["texto"] = datos["texto"].strip()

    resenas.update_one({"_id": ObjectId(resena_id)}, {"$set": cambios})
    return {"mensaje": "Reseña actualizada"}


# ─────────────────────────────────────────────────────────────────────────────
# RF3 – Eliminar reseña (por el cliente)
# DELETE /resenas/{resena_id}
# ─────────────────────────────────────────────────────────────────────────────
@app.delete("/resenas/{resena_id}")
def eliminar_resena_cliente(resena_id: str):
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada.")

    resenas.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {
            "estado":            "eliminada",
            "fecha_eliminacion": datetime.now(),
            "eliminado_por":     "cliente"
        }}
    )
    return {"mensaje": "Reseña eliminada"}


# ─────────────────────────────────────────────────────────────────────────────
# RF4 – Consultar reseñas de un hotel (público)
# GET /hoteles/{hotel_id}/resenas?orden=fecha|utilidad&pagina=1&por_pagina=10
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/hoteles/{hotel_id}/resenas")
def get_resenas_hotel(hotel_id: int, orden: str = "fecha", pagina: int = 1, por_pagina: int = 10):
    filtro = {"id_hotel": hotel_id, "estado": "publicada"}

    # Reseña destacada siempre va primero
    destacada = resenas.find_one({**filtro, "destacada": True}, {"_id": 1})

    sort_field = "fecha_creacion" if orden == "fecha" else "votos_utilidad"
    skip = (pagina - 1) * por_pagina

    docs = list(
        resenas.find(filtro, {"_id": 1, "calificacion": 1, "texto": 1,
                              "fecha_creacion": 1, "votos_utilidad": 1,
                              "respuesta_hotel": 1, "destacada": 1})
        .sort(sort_field, DESCENDING)
        .skip(skip)
        .limit(por_pagina)
    )

    resultado = []
    ids_vistos = set()

    # Primero la destacada (si existe y no es ya la primera)
    if destacada and pagina == 1:
        dest = resenas.find_one({"_id": destacada["_id"]},
                                {"_id": 1, "calificacion": 1, "texto": 1,
                                 "fecha_creacion": 1, "votos_utilidad": 1,
                                 "respuesta_hotel": 1, "destacada": 1})
        if dest:
            dest = serial(dest)
            dest["fecha_creacion"] = str(dest.get("fecha_creacion", ""))
            resultado.append(dest)
            ids_vistos.add(dest["_id"])

    for doc in docs:
        doc = serial(doc)
        doc["fecha_creacion"] = str(doc.get("fecha_creacion", ""))
        if doc["_id"] not in ids_vistos:
            resultado.append(doc)

    total = resenas.count_documents(filtro)
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "resenas": resultado}


# ─────────────────────────────────────────────────────────────────────────────
# RF5 – Marcar reseña como útil
# POST /resenas/{resena_id}/votos
# Body: { "id_usuario": int }
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/resenas/{resena_id}/votos")
def votar_resena(resena_id: str, datos: dict):
    id_usuario = int(datos.get("id_usuario", 0))
    if not id_usuario:
        raise HTTPException(status_code=400, detail="Se requiere id_usuario.")

    oid = ObjectId(resena_id)

    # Verificar que no haya votado antes
    if votos_utilidad.find_one({"id_resena": oid, "id_usuario": id_usuario}):
        raise HTTPException(status_code=400, detail="Ya votaste por esta reseña.")

    votos_utilidad.insert_one({
        "id_resena":  oid,
        "id_usuario": id_usuario,
        "fecha_voto": datetime.now()
    })
    # Incrementar contador en la reseña
    resenas.update_one({"_id": oid}, {"$inc": {"votos_utilidad": 1}})
    return {"mensaje": "Voto registrado"}


# ─────────────────────────────────────────────────────────────────────────────
# RF6 – Historial de reseñas propias del cliente
# GET /clientes/{cliente_id}/resenas?orden=fecha|hotel
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/clientes/{cliente_id}/resenas")
def get_resenas_cliente(cliente_id: int, orden: str = "fecha"):
    sort_field = "fecha_creacion" if orden == "fecha" else "id_hotel"
    docs = list(
        resenas.find(
            {"id_cliente": cliente_id},
            {"_id": 1, "id_hotel": 1, "calificacion": 1, "texto": 1,
             "estado": 1, "fecha_creacion": 1, "votos_utilidad": 1,
             "respuesta_hotel": 1}
        ).sort(sort_field, DESCENDING)
    )
    resultado = []
    for doc in docs:
        doc = serial(doc)
        doc["fecha_creacion"]  = str(doc.get("fecha_creacion", ""))
        doc["tiene_respuesta"] = doc.get("respuesta_hotel") is not None
        resultado.append(doc)
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# RF7 – Responder reseña (administrador)
# PUT /resenas/{resena_id}/respuesta
# Body: { "texto": str, "id_admin": str }
# ─────────────────────────────────────────────────────────────────────────────
@app.put("/resenas/{resena_id}/respuesta")
def responder_resena(resena_id: str, datos: dict):
    if not datos.get("texto") or len(datos["texto"].strip()) < 5:
        raise HTTPException(status_code=400, detail="La respuesta debe tener al menos 5 caracteres.")

    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada.")
    if resena["estado"] == "eliminada":
        raise HTTPException(status_code=400, detail="No se puede responder una reseña eliminada.")

    resenas.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {
            "respuesta_hotel": {
                "texto":    datos["texto"].strip(),
                "fecha":    datetime.now(),
                "id_admin": datos.get("id_admin", "admin")
            }
        }}
    )
    return {"mensaje": "Respuesta guardada"}


# ─────────────────────────────────────────────────────────────────────────────
# RF8 – Eliminar reseña (administrador)
# DELETE /admin/resenas/{resena_id}
# ─────────────────────────────────────────────────────────────────────────────
@app.delete("/admin/resenas/{resena_id}")
def eliminar_resena_admin(resena_id: str):
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada.")

    resenas.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {
            "estado":            "eliminada",
            "fecha_eliminacion": datetime.now(),
            "eliminado_por":     "administrador"
        }}
    )
    return {"mensaje": "Reseña eliminada por administrador"}


# ─────────────────────────────────────────────────────────────────────────────
# RF9 – Destacar / quitar destaque de una reseña
# PUT /resenas/{resena_id}/destacar
# Body: { "id_hotel": int, "destacar": bool }
# Solo puede haber una reseña destacada por hotel a la vez
# ─────────────────────────────────────────────────────────────────────────────
@app.put("/resenas/{resena_id}/destacar")
def destacar_resena(resena_id: str, datos: dict):
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada.")

    destacar = bool(datos.get("destacar", True))

    if destacar:
        # Quitar destaque a cualquier otra reseña del mismo hotel
        resenas.update_many(
            {"id_hotel": resena["id_hotel"], "destacada": True},
            {"$set": {"destacada": False}}
        )
        resenas.update_one({"_id": ObjectId(resena_id)}, {"$set": {"destacada": True}})
        return {"mensaje": "Reseña destacada"}
    else:
        resenas.update_one({"_id": ObjectId(resena_id)}, {"$set": {"destacada": False}})
        return {"mensaje": "Destaque quitado"}


# =============================================================================
# REQUERIMIENTOS DE CONSULTA (RFC)
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# RFC1 – Top 10 hoteles por calificación promedio en un período
# GET /analytics/top-hoteles?fecha_inicio=2024-01-01&fecha_fin=2024-12-31
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/analytics/top-hoteles")
def top_hoteles(fecha_inicio: str = "2024-01-01", fecha_fin: str = "2024-12-31"):
    pipeline = [
        {"$match": {
            "estado": "publicada",
            "fecha_creacion": {
                "$gte": datetime.fromisoformat(fecha_inicio),
                "$lte": datetime.fromisoformat(fecha_fin)
            }
        }},
        {"$group": {
            "_id":                    "$id_hotel",
            "calificacion_promedio":  {"$avg": "$calificacion"},
            "total_resenas":          {"$sum": 1},
            "total_votos":            {"$sum": "$votos_utilidad"}
        }},
        {"$sort": {"calificacion_promedio": -1, "total_resenas": -1}},
        {"$limit": 10},
        {"$project": {
            "_id": 0,
            "id_hotel":               "$_id",
            "calificacion_promedio":  {"$round": ["$calificacion_promedio", 2]},
            "total_resenas":          1,
            "total_votos":            1
        }}
    ]
    return list(resenas.aggregate(pipeline))


# ─────────────────────────────────────────────────────────────────────────────
# RFC2 – Evolución de reputación de un hotel mes a mes
# GET /analytics/evolucion/{hotel_id}?anio=2024
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/analytics/evolucion/{hotel_id}")
def evolucion_hotel(hotel_id: int, anio: int = 2024):
    pipeline = [
        {"$match": {
            "estado":    "publicada",
            "id_hotel":  hotel_id,
            "fecha_creacion": {
                "$gte": datetime(anio, 1, 1),
                "$lte": datetime(anio, 12, 31)
            }
        }},
        {"$group": {
            "_id":                   {"mes": {"$month": "$fecha_creacion"}},
            "calificacion_promedio": {"$avg": "$calificacion"},
            "total_resenas":         {"$sum": 1}
        }},
        {"$sort": {"_id.mes": 1}},
        {"$project": {
            "_id": 0,
            "mes":                   "$_id.mes",
            "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]},
            "total_resenas":         1
        }}
    ]
    return list(resenas.aggregate(pipeline))


# ─────────────────────────────────────────────────────────────────────────────
# RFC3 – Perfil comparativo de hoteles por ciudad
# GET /analytics/comparativo?hoteles=1,2,3
# (los IDs de hoteles de la ciudad vienen de Oracle vía APEX)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/analytics/comparativo")
def comparativo_ciudad(hoteles: str = "1,2"):
    ids = [int(x) for x in hoteles.split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="Se requiere al menos un id de hotel.")

    pipeline = [
        {"$match": {"estado": "publicada", "id_hotel": {"$in": ids}}},
        {"$facet": {
            "por_hotel": [
                {"$group": {
                    "_id":                   "$id_hotel",
                    "calificacion_promedio": {"$avg": "$calificacion"},
                    "total_resenas":         {"$sum": 1},
                    "con_respuesta":         {"$sum": {"$cond": [{"$ifNull": ["$respuesta_hotel", False]}, 1, 0]}},
                    "destacadas":            {"$sum": {"$cond": [{"$eq": ["$destacada", True]}, 1, 0]}}
                }},
                {"$project": {
                    "_id": 0,
                    "id_hotel":              "$_id",
                    "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]},
                    "total_resenas":         1,
                    "pct_respuesta":         {"$round": [{"$multiply": [{"$divide": ["$con_respuesta", "$total_resenas"]}, 100]}, 1]},
                    "pct_destacadas":        {"$round": [{"$multiply": [{"$divide": ["$destacadas",    "$total_resenas"]}, 100]}, 1]}
                }}
            ],
            "promedio_ciudad": [
                {"$group": {"_id": None, "prom": {"$avg": "$calificacion"}}}
            ]
        }},
        {"$unwind": "$por_hotel"},
        {"$addFields": {
            "por_hotel.promedio_ciudad": {"$round": [{"$arrayElemAt": ["$promedio_ciudad.prom", 0]}, 2]},
            "por_hotel.bajo_promedio":   {"$lt":    ["$por_hotel.calificacion_promedio",
                                                     {"$arrayElemAt": ["$promedio_ciudad.prom", 0]}]}
        }},
        {"$replaceRoot": {"newRoot": "$por_hotel"}},
        {"$sort": {"calificacion_promedio": -1}}
    ]
    return list(resenas.aggregate(pipeline))
