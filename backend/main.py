from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from typing import List, Optional
import shutil
import os
import uuid
import traceback
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataExtractor import EnhancedPDFExtractor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

@app.post("/autoparse_columns")
async def autoparse_columns(file: UploadFile = File(...)):
    """
    Accepts a PDF and returns suggested column names using AI
    """
    temp_filename = None
    upload_dir, _ = ensure_temp_dirs()
    try:
        # Save uploaded PDF
        if not file.filename.lower().endswith('.pdf'):
            return JSONResponse(status_code=400, content={"error": "Only PDF files are supported"})
        temp_filename = os.path.join(upload_dir, f"{uuid.uuid4()}_{file.filename}")
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print(f"[Autoparse] File saved as: {temp_filename}")

        # Use the first page for column suggestion
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return JSONResponse(status_code=500, content={"error": "Missing API key"})
        extractor = EnhancedPDFExtractor(api_key)
        images = extractor.pdf_to_images(temp_filename, dpi=200)
        if not images:
            return JSONResponse(status_code=500, content={"error": "Could not convert PDF to image"})
        image = images[0]

        # Prompt AI to suggest columns
        prompt = (
            "You are an expert at reading scientific tables in PDFs. "
            "Given the following page image, identify and return a JSON array of the most likely column names present in the table(s). "
            "Only return the array, no explanation."
        )
        base64_image = extractor.encode_image(image)
        response = extractor.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]}
            ],
            max_tokens=1024,
            temperature=0.1
        )
        response_text = response.choices[0].message.content.strip()
        # Try to extract JSON array from response
        import re, json
        match = re.search(r'\[(.*?)\]', response_text, re.DOTALL)
        if match:
            array_str = '[' + match.group(1) + ']'
            try:
                columns = json.loads(array_str)
                if isinstance(columns, list):
                    return {"columns": columns}
            except Exception as e:
                print(f"[Autoparse] JSON parse error: {e}")
        return JSONResponse(status_code=500, content={"error": "Could not parse columns from AI response", "raw": response_text})
    except Exception as e:
        print(f"[Autoparse] Error: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if temp_filename and os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except Exception as e:
                print(f"[Autoparse] Cleanup error: {e}")

# Frontend URL
FRONTEND_URL = "https://aiextractorfrontenddeploy.onrender.com"

# Allow frontend to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "http://localhost:3000",  # For local development
        "http://127.0.0.1:3000",  # For local development
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

def ensure_temp_dirs():
    """Create directories for file operations"""
    os.makedirs("uploaded", exist_ok=True)
    os.makedirs("extracted_tables", exist_ok=True)
    return "uploaded", "extracted_tables"


executor = ThreadPoolExecutor(max_workers=2)

def run_extraction(temp_filename: str, columns_list: List[str], extra_instructions: str, sample_pages: Optional[int] = None):
    """Run extraction in a separate thread to avoid blocking"""
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Missing OPENAI_API_KEY in environment variables.")
        
        extractor = EnhancedPDFExtractor(api_key)
        
        return extractor.process_pdf_enhanced(
            pdf_path=temp_filename,
            columns=columns_list,
            extra_instructions=extra_instructions,
            sample_pages=sample_pages
        )
    except Exception as e:
        print(f"Extraction error: {str(e)}")
        traceback.print_exc()
        raise e

@app.post("/extract")
async def extract_table(
    file: UploadFile = File(...),
    columns: str = Form(...),
    extra_instructions: str = Form(""),
    sample_pages: Optional[int] = Form(None)
):
    temp_filename = None
    upload_dir, extract_dir = ensure_temp_dirs()
    
    try:
        print(" Request received. Validating inputs...")
        print(f" Request from frontend: {FRONTEND_URL}")
        
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            return JSONResponse(
                status_code=400, 
                content={"error": "Only PDF files are supported"}
            )
        
        # Save the uploaded file to temporary directory
        temp_filename = os.path.join(upload_dir, f"{uuid.uuid4()}_{file.filename}")
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print(f"✅ File saved as: {temp_filename}")

        # Parse and validate column list
        try:
            columns_list = json.loads(columns)
            if not isinstance(columns_list, list) or not columns_list:
                raise ValueError("Columns must be a non-empty list")
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid columns format. Must be valid JSON array."}
            )
        
        print("📊 Columns requested:", columns_list)
        print("📝 Extra instructions:", extra_instructions)
        
        # Validate sample_pages
        if sample_pages is not None and sample_pages <= 0:
            sample_pages = None

        # Get and validate API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return JSONResponse(
                status_code=500,
                content={"error": "Server configuration error: Missing API key"}
            )
        print("🔑 API Key loaded successfully.")

        # Run extraction in thread pool to avoid blocking
        print(" Starting extraction process...")
        loop = asyncio.get_event_loop()
        output_excel_path = await loop.run_in_executor(
            executor,
            run_extraction,
            temp_filename,
            columns_list,
            extra_instructions,
            sample_pages
        )

        if output_excel_path and os.path.exists(output_excel_path):
            print(f"📤 Extraction complete. Returning: {output_excel_path}")
            
            return FileResponse(
                output_excel_path,
                filename=f"extracted_{file.filename.replace('.pdf', '.xlsx')}",
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={
                    "Content-Disposition": f"attachment; filename=extracted_{file.filename.replace('.pdf', '.xlsx')}",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Credentials": "true"
                }
            )
        else:
            print("❌ Extraction failed - no output file produced.")
            return JSONResponse(
                status_code=500, 
                content={"error": "Extraction failed. No data could be extracted from the PDF."}
            )

    except Exception as e:
        print(" Error during extraction:")
        traceback.print_exc()
        return JSONResponse(
            status_code=500, 
            content={"error": f"Server error: {str(e)}"}
        )
    finally:
        # Clean up uploaded file
        if temp_filename and os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
                print(f" Cleaned up temporary file: {temp_filename}")
            except Exception as e:
                print(f"Warning: Could not clean up {temp_filename}: {e}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    api_key = os.getenv("OPENAI_API_KEY")
    upload_dir, extract_dir = ensure_temp_dirs()
    
    return {
        "status": "healthy",
        "platform": "render",
        "frontend_url": FRONTEND_URL,
        "api_key_configured": bool(api_key),
        "upload_dir_exist": os.path.exists(upload_dir),
        "output_dir_exist": os.path.exists(extract_dir)
    }

@app.get("/")
async def root():
    return {
        "message": "PDF Table Extractor API is running",
        "platform": "render",
        "frontend_url": FRONTEND_URL,
        "cors_configured": True
    }

# Add a preflight handler for CORS
@app.options("/{full_path:path}")
async def options_handler():
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true"
        }
    )

# For local development
if __name__ == "__main__":
    import uvicorn
    # Use environment variable for port, default to 8000 when running locally
    port = int(os.getenv("PORT", 8000))
    print(f" Starting server on port {port}")
    print(f" Configured for frontend: {FRONTEND_URL}")
    uvicorn.run(app, host="0.0.0.0", port=port)

# Export for deployment
app = app



