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
import tempfile

# Load environment variables
load_dotenv()

app = FastAPI()

# Frontend URLs
FRONTEND_URL_PRIMARY = "https://aiextractorfrontenddeploy.onrender.com"
FRONTEND_URL_BACKUP = "https://ai-extractor-b5ec-2ldgmjfuw-bongiwe-mkwananzis-projects.vercel.app"

# Allow frontend to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL_PRIMARY,
        FRONTEND_URL_BACKUP,
        "https://aiextractorfrontenddeploy.onrender.com",  # primary URL
        "https://ai-extractor-b5ec-2ldgmjfuw-bongiwe-mkwananzis-projects.vercel.app",  # backup URL
        "http://localhost:3000",  # For local development
        "http://127.0.0.1:3000",  # For local development
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# For Vercel, use temporary directories instead of persistent folders
def ensure_temp_dirs():
    """Create temporary directories for file operations"""
    try:
        # On Vercel, use /tmp which is writable
        upload_dir = "/tmp/uploaded"
        extract_dir = "/tmp/extracted_tables"
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(extract_dir, exist_ok=True)
        return upload_dir, extract_dir
    except:
        # Fallback for local development
        os.makedirs("uploaded", exist_ok=True)
        os.makedirs("extracted_tables", exist_ok=True)
        return "uploaded", "extracted_tables"

# Global executor for running CPU-intensive tasks
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
        print("📥 Request received. Validating inputs...")
        print(f"🌐 Request from frontend - Primary: {FRONTEND_URL_PRIMARY}, Backup: {FRONTEND_URL_BACKUP}")
        
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
        print("🚀 Starting extraction process...")
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
            
            # Get the requesting origin for CORS
            request_origin = FRONTEND_URL_PRIMARY  # Default to primary
            
            return FileResponse(
                output_excel_path,
                filename=f"extracted_{file.filename.replace('.pdf', '.xlsx')}",
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={
                    "Content-Disposition": f"attachment; filename=extracted_{file.filename.replace('.pdf', '.xlsx')}",
                    "Access-Control-Allow-Origin": "*",  # Allow both frontends
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
        print("💥 Error during extraction:")
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
                print(f"🧹 Cleaned up temporary file: {temp_filename}")
            except Exception as e:
                print(f"Warning: Could not clean up {temp_filename}: {e}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    api_key = os.getenv("OPENAI_API_KEY")
    upload_dir, extract_dir = ensure_temp_dirs()
    
    return {
        "status": "healthy",
        "platform": "vercel" if os.getenv("VERCEL") else "local",
        "frontend_primary": FRONTEND_URL_PRIMARY,
        "frontend_backup": FRONTEND_URL_BACKUP,
        "api_key_configured": bool(api_key),
        "upload_dir_exist": os.path.exists(upload_dir),
        "output_dir_exist": os.path.exists(extract_dir)
    }

@app.get("/")
async def root():
    return {
        "message": "PDF Table Extractor API is running",
        "platform": "vercel" if os.getenv("VERCEL") else "local",
        "frontend_primary": FRONTEND_URL_PRIMARY,
        "frontend_backup": FRONTEND_URL_BACKUP,
        "cors_configured": True
    }

# Add a preflight handler for CORS
@app.options("/{full_path:path}")
async def options_handler():
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",  # Allow both frontends
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true"
        }
    )

# For local development
if __name__ == "__main__":
    import uvicorn
    # Use environment variable for port, default to 8000
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Starting server on port {port}")
    print(f"🌐 Configured for frontends - Primary: {FRONTEND_URL_PRIMARY}, Backup: {FRONTEND_URL_BACKUP}")
    uvicorn.run(app, host="0.0.0.0", port=port)

# Export for Vercel serverless functions
# This is crucial - Vercel looks for this
app = app
