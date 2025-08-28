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

# Simple CORS - allow your frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific IPs in production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Ensure folders exist
os.makedirs("uploaded", exist_ok=True)
os.makedirs("extracted_tables", exist_ok=True)

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
    try:
        print("📥 Request received. Validating inputs...")

        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            return JSONResponse(
                status_code=400, 
                content={"error": "Only PDF files are supported"}
            )

        # Save the uploaded file to disk
        temp_filename = f"uploaded/{uuid.uuid4()}_{file.filename}"
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
            return FileResponse(
                output_excel_path,
                filename=f"extracted_{file.filename.replace('.pdf', '.xlsx')}",
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={
                    "Content-Disposition": f"attachment; filename=extracted_{file.filename.replace('.pdf', '.xlsx')}"
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
    return {
        "status": "healthy",
        "api_key_configured": bool(api_key)
    }

@app.get("/")
async def root():
    return {"message": "PDF Table Extractor API is running"}

# Simple preflight handler
@app.options("/{full_path:path}")
async def options_handler():
    return JSONResponse(content={})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
