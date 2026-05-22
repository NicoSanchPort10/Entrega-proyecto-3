from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import MongoClient, DESCENDING
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime
import os

app = FastAPI(title="Dann-Alpes Reviews API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str, request: Request):
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
    )

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://ISIS2304A20202610:Fp6BX3fzAN7X@157.253.236.88:8087")
MONGO_DB  = os.environ.get("MONGO_DB",  "ISIS2304A20202610")

client = MongoClient(MONGO_URI)
db     = client[MONGO_DB]

resenas        = db["resenas"]
votos_utilidad = db["votos_utilidad"]

def serial(doc):
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc

class VotoData(BaseModel):
    id_usuario: int

class ResenaData(BaseModel):
    id_cliente: int
    id_reserva: int
    calificacion: int
    texto: str

class EditarResenaData(BaseModel):
    calificacion: int = None
    texto: str = None

class RespuestaData(BaseModel):
    texto: str
    id_admin: str = "admin"

class DestacaData(BaseModel):
    destacar: bool = True
    id_hotel: int = None

# =============================================================================
# ENDPOINTS DEL TALLER ANTERIOR (Parranderos)
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

@app.post("/hoteles/{hotel_id}/resenas")
def crear_resena(hotel_id: int, datos: ResenaData):
    if resenas.find_one({"id_reserva": datos.id_reserva}):
        raise HTTPException(status_code=400, detail="Ya existe una resena para esta reserva.")
    if not (1 <= datos.calificacion <= 5):
        raise HTTPException(status_code=400, detail="La calificacion debe estar entre 1 y 5.")
    if len(datos.texto.strip()) < 10:
        raise HTTPException(status_code=400, detail="El texto debe tener al menos 10 caracteres.")
    doc = {
        "id_hotel":       hotel_id,
        "id_cliente":     datos.id_cliente,
        "id_reserva":     datos.id_reserva,
        "calificacion":   datos.calificacion,
        "texto":          datos.texto.strip(),
        "estado":         "publicada",
        "fecha_creacion": datetime.now(),
        "votos_utilidad": 0,
        "destacada":      False
    }
    resultado = resenas.insert_one(doc)
    return {"mensaje": "Resena creada", "id": str(resultado.inserted_id)}

@app.put("/resenas/{resena_id}")
def editar_resena(resena_id: str, datos: EditarResenaData):
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Resena no encontrada.")
    if resena["estado"] == "eliminada":
        raise HTTPException(status_code=400, detail="No se puede editar una resena eliminada.")
    cambios = {"fecha_modificacion": datetime.now()}
    if datos.calificacion is not None:
        if not (1 <= datos.calificacion <= 5):
            raise HTTPException(status_code=400, detail="La calificacion debe estar entre 1 y 5.")
        cambios["calificacion"] = datos.calificacion
    if datos.texto is not None:
        if len(datos.texto.strip()) < 10:
            raise HTTPException(status_code=400, detail="El texto debe tener al menos 10 caracteres.")
        cambios["texto"] = datos.texto.strip()
    resenas.update_one({"_id": ObjectId(resena_id)}, {"$set": cambios})
    return {"mensaje": "Resena actualizada"}

@app.delete("/resenas/{resena_id}")
def eliminar_resena_cliente(resena_id: str):
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Resena no encontrada.")
    resenas.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {"estado": "eliminada", "fecha_eliminacion": datetime.now(), "eliminado_por": "cliente"}}
    )
    return {"mensaje": "Resena eliminada"}

@app.get("/hoteles/{hotel_id}/resenas")
def get_resenas_hotel(hotel_id: int, orden: str = "fecha", pagina: int = 1, por_pagina: int = 10):
    filtro = {"id_hotel": hotel_id, "estado": "publicada"}
    destacada = resenas.find_one({**filtro, "destacada": True}, {"_id": 1})
    sort_field = "fecha_creacion" if orden == "fecha" else "votos_utilidad"
    skip = (pagina - 1) * por_pagina
    docs = list(
        resenas.find(filtro, {"_id": 1, "calificacion": 1, "texto": 1,
                              "fecha_creacion": 1, "votos_utilidad": 1,
                              "respuesta_hotel": 1, "destacada": 1})
        .sort(sort_field, DESCENDING).skip(skip).limit(por_pagina)
    )
    resultado = []
    ids_vistos = set()
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

@app.post("/resenas/{resena_id}/votos")
def votar_resena(resena_id: str, datos: VotoData):
    oid = ObjectId(resena_id)
    if votos_utilidad.find_one({"id_resena": oid, "id_usuario": datos.id_usuario}):
        raise HTTPException(status_code=400, detail="Ya votaste por esta resena.")
    votos_utilidad.insert_one({
        "id_resena":  oid,
        "id_usuario": datos.id_usuario,
        "fecha_voto": datetime.now()
    })
    resenas.update_one({"_id": oid}, {"$inc": {"votos_utilidad": 1}})
    return {"mensaje": "Voto registrado"}

@app.get("/clientes/{cliente_id}/resenas")
def get_resenas_cliente(cliente_id: int, orden: str = "fecha"):
    sort_field = "fecha_creacion" if orden == "fecha" else "id_hotel"
    docs = list(
        resenas.find(
            {"id_cliente": cliente_id},
            {"_id": 1, "id_hotel": 1, "calificacion": 1, "texto": 1,
             "estado": 1, "fecha_creacion": 1, "votos_utilidad": 1, "respuesta_hotel": 1}
        ).sort(sort_field, DESCENDING)
    )
    resultado = []
    for doc in docs:
        doc = serial(doc)
        doc["fecha_creacion"]  = str(doc.get("fecha_creacion", ""))
        doc["tiene_respuesta"] = doc.get("respuesta_hotel") is not None
        resultado.append(doc)
    return resultado

@app.put("/resenas/{resena_id}/respuesta")
def responder_resena(resena_id: str, datos: RespuestaData):
    if len(datos.texto.strip()) < 5:
        raise HTTPException(status_code=400, detail="La respuesta debe tener al menos 5 caracteres.")
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Resena no encontrada.")
    if resena["estado"] == "eliminada":
        raise HTTPException(status_code=400, detail="No se puede responder una resena eliminada.")
    resenas.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {"respuesta_hotel": {"texto": datos.texto.strip(), "fecha": datetime.now(), "id_admin": datos.id_admin}}}
    )
    return {"mensaje": "Respuesta guardada"}

@app.delete("/admin/resenas/{resena_id}")
def eliminar_resena_admin(resena_id: str):
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Resena no encontrada.")
    resenas.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {"estado": "eliminada", "fecha_eliminacion": datetime.now(), "eliminado_por": "administrador"}}
    )
    return {"mensaje": "Resena eliminada por administrador"}

@app.put("/resenas/{resena_id}/destacar")
def destacar_resena(resena_id: str, datos: DestacaData):
    resena = resenas.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Resena no encontrada.")
    if datos.destacar:
        resenas.update_many({"id_hotel": resena["id_hotel"], "destacada": True}, {"$set": {"destacada": False}})
        resenas.update_one({"_id": ObjectId(resena_id)}, {"$set": {"destacada": True}})
        return {"mensaje": "Resena destacada"}
    else:
        resenas.update_one({"_id": ObjectId(resena_id)}, {"$set": {"destacada": False}})
        return {"mensaje": "Destaque quitado"}

@app.get("/analytics/top-hoteles")
def top_hoteles(fecha_inicio: str = "2024-01-01", fecha_fin: str = "2024-12-31"):
    pipeline = [
        {"$match": {"estado": "publicada", "fecha_creacion": {"$gte": datetime.fromisoformat(fecha_inicio), "$lte": datetime.fromisoformat(fecha_fin)}}},
        {"$group": {"_id": "$id_hotel", "calificacion_promedio": {"$avg": "$calificacion"}, "total_resenas": {"$sum": 1}, "total_votos": {"$sum": "$votos_utilidad"}}},
        {"$sort": {"calificacion_promedio": -1, "total_resenas": -1}},
        {"$limit": 10},
        {"$project": {"_id": 0, "id_hotel": "$_id", "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]}, "total_resenas": 1, "total_votos": 1}}
    ]
    return list(resenas.aggregate(pipeline))

@app.get("/analytics/evolucion/{hotel_id}")
def evolucion_hotel(hotel_id: int, anio: int = 2024):
    pipeline = [
        {"$match": {"estado": "publicada", "id_hotel": hotel_id, "fecha_creacion": {"$gte": datetime(anio, 1, 1), "$lte": datetime(anio, 12, 31)}}},
        {"$group": {"_id": {"mes": {"$month": "$fecha_creacion"}}, "calificacion_promedio": {"$avg": "$calificacion"}, "total_resenas": {"$sum": 1}}},
        {"$sort": {"_id.mes": 1}},
        {"$project": {"_id": 0, "mes": "$_id.mes", "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]}, "total_resenas": 1}}
    ]
    return list(resenas.aggregate(pipeline))

@app.get("/analytics/comparativo")
def comparativo_ciudad(hoteles: str = "1,2"):
    ids = [int(x) for x in hoteles.split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="Se requiere al menos un id de hotel.")
    pipeline = [
        {"$match": {"estado": "publicada", "id_hotel": {"$in": ids}}},
        {"$facet": {
            "por_hotel": [
                {"$group": {"_id": "$id_hotel", "calificacion_promedio": {"$avg": "$calificacion"}, "total_resenas": {"$sum": 1},
                    "con_respuesta": {"$sum": {"$cond": [{"$ifNull": ["$respuesta_hotel", False]}, 1, 0]}},
                    "destacadas": {"$sum": {"$cond": [{"$eq": ["$destacada", True]}, 1, 0]}}}},
                {"$project": {"_id": 0, "id_hotel": "$_id", "calificacion_promedio": {"$round": ["$calificacion_promedio", 2]},
                    "total_resenas": 1,
                    "pct_respuesta": {"$round": [{"$multiply": [{"$divide": ["$con_respuesta", "$total_resenas"]}, 100]}, 1]},
                    "pct_destacadas": {"$round": [{"$multiply": [{"$divide": ["$destacadas", "$total_resenas"]}, 100]}, 1]}}}
            ],
            "promedio_ciudad": [{"$group": {"_id": None, "prom": {"$avg": "$calificacion"}}}]
        }},
        {"$unwind": "$por_hotel"},
        {"$addFields": {
            "por_hotel.promedio_ciudad": {"$round": [{"$arrayElemAt": ["$promedio_ciudad.prom", 0]}, 2]},
            "por_hotel.bajo_promedio": {"$lt": ["$por_hotel.calificacion_promedio", {"$arrayElemAt": ["$promedio_ciudad.prom", 0]}]}
        }},
        {"$replaceRoot": {"newRoot": "$por_hotel"}},
        {"$sort": {"calificacion_promedio": -1}}
    ]
    return list(resenas.aggregate(pipeline))
