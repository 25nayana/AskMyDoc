from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from pydantic import BaseModel
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import ConversationalRetrievalChain
from langchain_core.messages import AIMessage, HumanMessage
from langchain_community.vectorstores import FAISS
from utils.functions import load_pdf, load_docx, text_split, vectorstore_create, format_chat
from logging.handlers import RotatingFileHandler
from utils.prompt import custom_prompt
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv
import traceback
import logging
import os
import shutil

handler = RotatingFileHandler('myapp.log', maxBytes=5*1024*1024, backupCount=2)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)
db = client["chat_db"]
chat_collection = db["chat_history"]

load_dotenv()

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
app = FastAPI()
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vectorstore = None
chat_history=[]

class QuestionRequest(BaseModel):
    question: str
    user_id: str

@app.post("/get")
async def upload_documents(user_id: str = Form(...), file: UploadFile = File(...)):
    global vectorstore

    UPLOAD_DIR = f"temp_uploads/{user_id}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    filename = file.filename
    ext = filename.split('.')[-1].lower()
    
    if ext not in ["pdf", "docx"]:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    temp_file_path = os.path.join(UPLOAD_DIR, filename)
    with open(temp_file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    if ext == "pdf":
        pages = load_pdf(temp_file_path)
    else:
        pages = load_docx(temp_file_path)

    texts = text_split(pages)
    vectorstore_create(user_id,texts)
    vectorstore = FAISS.load_local(f"db/{user_id}", embeddings, allow_dangerous_deserialization=True)

    logger.info(f"File {filename} logged in at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return {"message": "Vectorstore created successfully"}

@app.post("/chat")
def chat_function(req: QuestionRequest):
    global vectorstore

    question = req.question
    user_id = req.user_id

    chat_history = chat_collection.find_one({"user_id": user_id})
    chat = chat_history["chat"] if chat_history and "chat" in chat_history else []

    if not chat:
        vectorstore = None

    formatted_chat = format_chat(chat)
    visible_chat = formatted_chat[-15:] if len(formatted_chat) > 15 else formatted_chat

    if question == "clear":
        try:
            shutil.rmtree(f"db/{user_id}", ignore_errors=True)
            shutil.rmtree(f"temp_uploads/{user_id}", ignore_errors=True)
            vectorstore=None
            assistant_reply = "Your file uploads cleared."
        except Exception as e:
            error_str = traceback.format_exc().strip().split("\n")[-1]
            print(f"Error while clearing: {error_str}")
            assistant_reply = f"An error occurred while clearing: {error_str}"

        chat_entry = {"role": "user", "content": question}
        reply_entry = {"role": "assistant", "content": assistant_reply}

        chat_collection.update_one(
            {"user_id": user_id},
            {
                "$push": {
                    "chat": {"$each": [chat_entry, reply_entry]}
                }
            },
            upsert=True
        )

        return {"answer": assistant_reply}

    try:
        if vectorstore is None:
            vectorstore = FAISS.load_local(f"db/{user_id}", embeddings, allow_dangerous_deserialization=True)

        retriever = vectorstore.as_retriever()
        chain = ConversationalRetrievalChain.from_llm(
            llm,
            retriever=retriever,
            combine_docs_chain_kwargs={"prompt": custom_prompt},
            verbose=True
        )

        result = chain.invoke({"question": question, "chat_history": visible_chat})

        chat_entry = {"role": "user", "content": question}
        reply_entry = {"role": "assistant", "content": result['answer']}

        chat_collection.update_one(
            {"user_id": user_id},
            {
                "$push": {
                    "chat": {"$each": [chat_entry, reply_entry]}
                }
            },
            upsert=True
        )

        return {"answer": result["answer"]}

    except Exception as e:
        error_message = str(e).split(":")[-1].strip()
        chat_entry = {"role": "user", "content": question}
        reply_entry = {"role": "assistant", "content": error_message}

        chat_collection.update_one(
            {"user_id": user_id},
            {
                "$push": {
                    "chat": {"$each": [chat_entry, reply_entry]}
                }
            },
            upsert=True
        )

        return {"answer": error_message}