import React, { useState } from "react";
import axios from "axios";
import * as XLSX from "xlsx";

function App() {
  const [pdfFile, setPdfFile] = useState(null);
  const [columns, setColumns] = useState("Species,Common Name,Location,Status");
  const [notes, setNotes] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [downloadLink, setDownloadLink] = useState("");
  const [previewData, setPreviewData] = useState([]);
  const [extractedBlob, setExtractedBlob] = useState(null);
  const [originalFilename, setOriginalFilename] = useState("");
  const [extractionStats, setExtractionStats] = useState(null);
  const [error, setError] = useState("");
  const [samplePages, setSamplePages] = useState("");

  // Define the backend URL at the top
  const BACKEND_URL = "https://aiextractorautomationpipeline.onrender.com";

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    setPdfFile(file);
    setOriginalFilename(file ? file.name : "");
    setError("");
    // Reset previous results
    setDownloadLink("");
    setPreviewData([]);
    setExtractedBlob(null);
    setExtractionStats(null);
  };

  const validateInputs = () => {
    if (!pdfFile) {
      setError("Please select a PDF file");
      return false;
    }
    
    if (!pdfFile.name.toLowerCase().endsWith('.pdf')) {
      setError("Please select a valid PDF file");
      return false;
    }
    
    if (!columns.trim()) {
      setError("Please specify at least one column");
      return false;
    }
    
    const columnList = columns.split(',').map(c => c.trim()).filter(c => c);
    if (columnList.length === 0) {
      setError("Please specify valid column names");
      return false;
    }
    
    if (samplePages && (isNaN(samplePages) || parseInt(samplePages) <= 0)) {
      setError("Sample pages must be a positive number");
      return false;
    }
    
    return true;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!validateInputs()) {
      return;
    }
    
    setIsLoading(true);
    setDownloadLink("");
    setPreviewData([]);
    setExtractedBlob(null);
    setExtractionStats(null);
    setError("");

    const formData = new FormData();
    formData.append("file", pdfFile);
    
    // Parse columns and send as JSON
    const columnList = columns.split(',').map(c => c.trim()).filter(c => c);
    formData.append("columns", JSON.stringify(columnList));
    formData.append("extra_instructions", notes);
    
    if (samplePages && !isNaN(samplePages) && parseInt(samplePages) > 0) {
      formData.append("sample_pages", parseInt(samplePages));
    }

    try {
      console.log("Sending extraction request...");
      console.log("Backend URL:", BACKEND_URL);
      console.log("Form data:", {
        file: pdfFile.name,
        columns: columnList,
        extra_instructions: notes,
        sample_pages: samplePages ? parseInt(samplePages) : null
      });
      
      // Use the BACKEND_URL instead of localhost
      const response = await axios.post(`${BACKEND_URL}/extract`, formData, {
        responseType: "blob",
        timeout: 300000, // 5 minutes timeout
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          console.log(`Upload progress: ${Math.round((progressEvent.loaded * 100) / progressEvent.total)}%`);
        }
      });

      console.log("Extraction completed successfully");
      
      // Store the blob for download
      setExtractedBlob(response.data);
      
      // Create download link for preview (will be cleaned up properly)
      const link = URL.createObjectURL(response.data);
      setDownloadLink(link);

      // Read Excel data and set preview
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const data = new Uint8Array(e.target.result);
          const workbook = XLSX.read(data, { type: "array" });
          const sheet = workbook.Sheets[workbook.SheetNames[0]];
          const json = XLSX.utils.sheet_to_json(sheet, { header: 1 });
          
          setPreviewData(json);
          
          // Calculate stats
          const stats = {
            totalRows: json.length > 0 ? json.length - 1 : 0, // Subtract header row
            totalColumns: json.length > 0 ? json[0].length : 0,
            hasData: json.length > 1
          };
          setExtractionStats(stats);
          
          console.log(`Preview loaded: ${stats.totalRows} rows, ${stats.totalColumns} columns`);
        } catch (err) {
          console.error("Error parsing Excel data:", err);
          setError("Could not parse extracted data for preview");
        }
      };
      reader.readAsArrayBuffer(response.data);

    } catch (error) {
      console.error("Extraction failed:", error);
      console.error("Error details:", {
        message: error.message,
        response: error.response ? {
          status: error.response.status,
          statusText: error.response.statusText,
          headers: error.response.headers
        } : null,
        request: error.request ? "Request made but no response" : null
      });
      
      if (error.response) {
        // Server responded with error
        if (error.response.data instanceof Blob) {
          // Try to read error message from blob
          try {
            const text = await error.response.data.text();
            console.log("Error response text:", text);
            try {
              const errorData = JSON.parse(text);
              setError(`Extraction failed: ${errorData.error || errorData.message || 'Unknown error'}`);
            } catch {
              setError(`Extraction failed: ${error.response.status} ${error.response.statusText}`);
            }
          } catch (blobError) {
            console.error("Error reading blob:", blobError);
            setError(`Extraction failed: ${error.response.status} ${error.response.statusText}`);
          }
        } else {
          setError(`Extraction failed: ${error.response.data?.error || error.response.statusText || 'Server error'}`);
        }
      } else if (error.request) {
        setError(`No response from server. Please check if the backend is running at ${BACKEND_URL}`);
      } else {
        setError(`Request failed: ${error.message}`);
      }
    }

    setIsLoading(false);
  };

  const handleDownload = () => {
    if (extractedBlob && originalFilename) {
      const a = document.createElement('a');
      const url = URL.createObjectURL(extractedBlob);
      a.href = url;
      a.download = `extracted_${originalFilename.replace('.pdf', '.xlsx')}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  };

  const handleDiscard = () => {
    setDownloadLink("");
    setPreviewData([]);
    setExtractedBlob(null);
    setExtractionStats(null);
    if (downloadLink) {
      URL.revokeObjectURL(downloadLink);
    }
  };

  const renderPreviewTable = () => {
    if (previewData.length === 0) return null;
    
    const maxPreviewRows = 20; // Limit preview to first 20 rows
    const previewRows = previewData.slice(0, maxPreviewRows);
    
    return (
      <div style={{ marginTop: "2rem", overflowX: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h4>📄 Extraction Preview</h4>
          {extractionStats && (
            <div style={{ fontSize: "0.9em", color: "#666" }}>
              {extractionStats.totalRows} rows × {extractionStats.totalColumns} columns
              {previewData.length > maxPreviewRows && ` (showing first ${maxPreviewRows} rows)`}
            </div>
          )}
        </div>
        
        <table 
          border="1" 
          cellPadding="8" 
          cellSpacing="0" 
          style={{ 
            borderCollapse: "collapse", 
            width: "100%",
            fontSize: "0.9em",
            maxHeight: "400px",
            display: "block",
            overflowY: "auto"
          }}
        >
          <thead style={{ position: "sticky", top: 0, backgroundColor: "#f5f5f5" }}>
            {previewRows.length > 0 && (
              <tr>
                {previewRows[0].map((header, j) => (
                  <th key={j} style={{ 
                    padding: "8px", 
                    backgroundColor: "#e0e0e0", 
                    fontWeight: "bold",
                    minWidth: "120px"
                  }}>
                    {header}
                  </th>
                ))}
              </tr>
            )}
          </thead>
          <tbody style={{ display: "table", width: "100%" }}>
            {previewRows.slice(1).map((row, i) => (
              <tr key={i} style={{ backgroundColor: i % 2 === 0 ? "#f9f9f9" : "white" }}>
                {row.map((cell, j) => (
                  <td key={j} style={{ 
                    padding: "6px 8px", 
                    borderBottom: "1px solid #ddd",
                    minWidth: "120px",
                    wordBreak: "break-word"
                  }}>
                    {cell || "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        
        {previewData.length > maxPreviewRows && (
          <div style={{ textAlign: "center", padding: "1rem", fontStyle: "italic", color: "#666" }}>
            ... and {previewData.length - maxPreviewRows} more rows. Download the full file to see all data.
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ 
      padding: "2rem", 
      fontFamily: "Arial, sans-serif", 
      maxWidth: "1000px", 
      margin: "auto",
      backgroundColor: "#fafafa",
      minHeight: "100vh"
    }}>
      <div style={{ 
        backgroundColor: "white", 
        padding: "2rem", 
        borderRadius: "8px", 
        boxShadow: "0 2px 4px rgba(0,0,0,0.1)" 
      }}>
        <h2 style={{ color: "#333", marginBottom: "1.5rem" }}>🔍 PDF Table Extractor</h2>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: "bold" }}>
              Upload PDF:
            </label>
            <input 
              type="file" 
              accept="application/pdf" 
              onChange={handleFileChange} 
              required 
              style={{ 
                padding: "0.5rem", 
                border: "2px dashed #ccc", 
                borderRadius: "4px",
                width: "100%",
                backgroundColor: "#f9f9f9"
              }}
            />
            {pdfFile && (
              <div style={{ marginTop: "0.5rem", fontSize: "0.9em", color: "#666" }}>
                Selected: {pdfFile.name} ({(pdfFile.size / 1024 / 1024).toFixed(2)} MB)
              </div>
            )}
          </div>

          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: "bold" }}>
              Columns (comma-separated):
            </label>
            <input 
              type="text" 
              value={columns} 
              onChange={(e) => setColumns(e.target.value)} 
              style={{ 
                width: "100%", 
                padding: "0.75rem", 
                border: "1px solid #ddd", 
                borderRadius: "4px",
                fontSize: "1em"
              }}
              placeholder="e.g., Species, Common Name, Location, Status"
            />
            <div style={{ fontSize: "0.8em", color: "#666", marginTop: "0.25rem" }}>
              Example: Species, Common Name, Location, Status
            </div>
          </div>

          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: "bold" }}>
              Test Mode - Sample Pages (optional):
            </label>
            <input 
              type="number" 
              value={samplePages} 
              onChange={(e) => setSamplePages(e.target.value)} 
              style={{ 
                width: "200px", 
                padding: "0.75rem", 
                border: "1px solid #ddd", 
                borderRadius: "4px",
                fontSize: "1em"
              }}
              placeholder="e.g., 3"
              min="1"
            />
            <div style={{ fontSize: "0.8em", color: "#666", marginTop: "0.25rem" }}>
              Leave empty to process all pages. Enter a number to test with first N pages only.
            </div>
          </div>

          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: "bold" }}>
              Extra Instructions (optional):
            </label>
            <textarea 
              value={notes} 
              onChange={(e) => setNotes(e.target.value)} 
              rows="4" 
              style={{ 
                width: "100%", 
                padding: "0.75rem", 
                border: "1px solid #ddd", 
                borderRadius: "4px",
                fontSize: "1rem",
                resize: "vertical"
              }}
              placeholder="Any specific instructions for data extraction..."
            />
          </div>

          {error && (
            <div style={{ 
              marginBottom: "1rem", 
              padding: "1rem", 
              backgroundColor: "#fee", 
              border: "1px solid #fcc", 
              borderRadius: "4px",
              color: "#c00"
            }}>
              ❌ {error}
            </div>
          )}

          <button 
            type="submit" 
            disabled={isLoading}
            style={{ 
              padding: "1rem 2rem", 
              backgroundColor: isLoading ? "#ccc" : "#007bff", 
              color: "white", 
              border: "none", 
              borderRadius: "4px",
              fontSize: "1.1em",
              cursor: isLoading ? "not-allowed" : "pointer",
              transition: "background-color 0.2s"
            }}
          >
            {isLoading ? "🔄 Extracting...grab some water or doom scroll, it maybe a minute" : "🚀 Extract Table"}
          </button>
        </form>

        {isLoading && (
          <div style={{ 
            marginTop: "2rem", 
            padding: "1rem", 
            backgroundColor: "#e3f2fd", 
            border: "1px solid #2196f3", 
            borderRadius: "4px",
            textAlign: "center"
          }}>
            <div>⏳ Processing your PDF... This may take a few minutes.</div>
            <div style={{ fontSize: "0.9em", color: "#666", marginTop: "0.5rem" }}>
              Please don't close this window while extraction is in progress.
            </div>
          </div>
        )}

        {extractionStats && !isLoading && (
          <div style={{ 
            marginTop: "2rem", 
            padding: "1rem", 
            backgroundColor: "#e8f5e8", 
            border: "1px solid #4caf50", 
            borderRadius: "4px"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong>✅ Extraction Complete!</strong>
                <div style={{ fontSize: "0.9em", color: "#666", marginTop: "0.25rem" }}>
                  Found {extractionStats.totalRows} rows of data
                </div>
              </div>
              <div>
                <button 
                  onClick={handleDownload}
                  style={{ 
                    padding: "0.75rem 1.5rem", 
                    backgroundColor: "#28a745", 
                    color: "white", 
                    border: "none", 
                    borderRadius: "4px",
                    marginRight: "0.5rem",
                    cursor: "pointer",
                    fontSize: "1em"
                  }}
                >
                  ⬇️ Download Excel
                </button>
                <button 
                  onClick={handleDiscard}
                  style={{ 
                    padding: "0.75rem 1.5rem", 
                    backgroundColor: "#dc3545", 
                    color: "white", 
                    border: "none", 
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "1em"
                  }}
                >
                  ❌ Discard
                </button>
              </div>
            </div>
          </div>
        )}

        {renderPreviewTable()}
      </div>
    </div>
  );
}

export default App;
