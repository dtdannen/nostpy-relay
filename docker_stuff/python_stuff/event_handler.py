import os
import json
import logging
import redis
from ddtrace import tracer
import aiohttp
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker, class_mapper
from sqlalchemy import create_engine, Column, String, Integer, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError


tracer.configure(hostname='172.28.0.5', port=8126)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logging.basicConfig(level=logging.DEBUG)

DATABASE_URL = os.environ.get("DATABASE_URL")
logger.debug(f"DATABASE_URL value: {DATABASE_URL}")

redis_client = redis.Redis(host='172.28.0.6', port=6379)

engine = create_engine(DATABASE_URL, echo=True)
Base = declarative_base()


class Event(Base):
    __tablename__ = 'event'

    id = Column(String, primary_key=True, index=True)
    pubkey = Column(String, index=True)
    kind = Column(Integer, index=True)
    created_at = Column(Integer, index=True)
    tags = Column(JSON)
    content = Column(String)
    sig = Column(String)

    def __init__(self, id: str, pubkey: str, kind: int, created_at: int, tags: list, content: str, sig: str):
        self.id = id
        self.pubkey = pubkey
        self.kind = kind
        self.created_at = created_at
        self.tags = tags
        self.content = content
        self.sig = sig

logger.debug("Creating database metadata")
Base.metadata.create_all(bind=engine)

app = FastAPI()

@app.post("/new_event")
async def handle_new_event(request: Request):
    event_dict = await request.json()
    pubkey = event_dict.get("pubkey")
    kind = event_dict.get("kind")
    created_at = event_dict.get("created_at")
    tags = event_dict.get("tags")
    content = event_dict.get("content")
    event_id = event_dict.get("id")
    sig = event_dict.get("sig")

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        delete_message = None
        if kind in {0, 3}:
            delete_message = f"Deleting existing metadata for pubkey {pubkey}"
            session.query(Event).filter_by(pubkey=pubkey, kind=kind).delete()

        existing_event = session.query(Event).filter_by(id=event_id).scalar()
        if existing_event is not None:
            raise HTTPException(status_code=409, detail=f"Event with ID {event_id} already exists")

        new_event = Event(
            id=event_id,
            pubkey=pubkey,
            kind=kind,
            created_at=created_at,
            tags=tags,
            content=content,
            sig=sig
        )

        session.add(new_event)
        session.commit()
        
        message = "Event added successfully" if kind == 1 else "Event updated successfully"
        response = {"message": message}
        return JSONResponse(content=response, status_code=200)
    
    except SQLAlchemyError as e:
        logger.exception(f"Error saving event: {e}")
        raise HTTPException(status_code=500, detail="Failed to save event to database")

    finally:
        if delete_message:
            logger.debug(delete_message.format(pubkey=pubkey))
        session.close()


def serialize(model):
    # Helper function to convert an SQLAlchemy model instance to a dictionary
    columns = [c.key for c in class_mapper(model.__class__).columns]
    return dict((c, getattr(model, c)) for c in columns)
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80)