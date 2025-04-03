import os
import time
import json
import tempfile
from flask import Flask, request, send_file, jsonify
from google.cloud import storage
import google.generativeai as genai

# Load API key from environment variable (do not hardcode)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # Ensure this is set in your environment
if not GEMINI_API_KEY:
    raise ValueError("Missing Gemini API Key. Set GEMINI_API_KEY.")

genai.configure(api_key=GEMINI_API_KEY)

# Google Cloud Configuration
PROJECT_ID = "project2-452119"
BUCKET_NAME = "project2-452119-bucket"
REGION = "us-central1"

# Initialize Flask
app = Flask(__name__)

# Initialize Google Cloud Storage client
storage_client = storage.Client()

### Cloud Storage Functions ###
def upload_blob(bucket_name, source_file, destination_blob):
    """Uploads a file to Google Cloud Storage."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob)
    blob.upload_from_filename(source_file)
    print(f"Uploaded {destination_blob} to bucket {bucket_name}.")

def download_blob(bucket_name, source_blob_name, destination_file_name):
    """Downloads a file from Google Cloud Storage."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(source_blob_name)
    if not blob.exists():
        print(f"File {source_blob_name} not found in bucket {bucket_name}.")
        return None
    blob.download_to_filename(destination_file_name)
    print(f"Downloaded {source_blob_name} to {destination_file_name}")
    return destination_file_name

def list_blobs(bucket_name):
    """Lists all blobs (files) in the Cloud Storage bucket."""
    bucket = storage_client.bucket(bucket_name)
    return [blob.name for blob in bucket.list_blobs() if blob.name.endswith((".jpeg", ".jpg"))]

### Gemini AI Functions ###
def upload_to_gemini(path, mime_type="image/jpeg"):
    """Uploads an image file to Gemini AI and returns the uploaded file object."""
    try:
        file = genai.upload_file(path, mime_type=mime_type)
        if not file:
            raise ValueError("Upload failed: No file returned from Gemini AI.")
        print(f"Uploaded file '{file.display_name}' as: {file.uri}")
        return file
    except Exception as e:
        print(f"Error uploading to Gemini AI: {e}")
        return None

def generate_gemini_caption(image_path, mime_type="image/jpeg"):
    """Generates a title and description from the Gemini multimodal model."""
    try:
        # Optional: define generation configuration if needed
        generation_config = {
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 64,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        }
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            # generation_config=generation_config,
        )
        # Define the prompt
        PROMPT = "describe the image. end your response in json"
        # Upload the image to Gemini and get the uploaded file object
        gemini_file = upload_to_gemini(image_path, mime_type=mime_type)
        if gemini_file is None:
            return {"title": "Upload Failed", "description": "Could not generate description due to upload error."}
        # Generate content using the model, mimicking your provided snippet
        response = model.generate_content([
            gemini_file,  # The uploaded file object
            "\n\n",
            PROMPT
        ])
        # Debug: print response type and content
        print("Debug: Response type:", type(response))
        print("Debug: Response content:", response)
        # Process the response to extract text
        result_text = response.text.strip()
        # Split the result text into a title and description if possible
        if ". " in result_text:
            title, description = result_text.split(". ", 1)
        else:
            title, description = "Generated Title", result_text
        return {"title": title.strip(), "description": description.strip()}
    except Exception as e:
        print(f"Error processing image with Gemini AI: {e}")
        return {"title": "Error", "description": "An error occurred while generating the description."}

### Flask Routes ###
@app.route('/')
def index():
    """Displays uploaded images with links to view, download, or get JSON metadata."""
    # Retrieve background color from environment variable (set externally in deployment)
    background_color = os.environ.get("BACKGROUND_COLOR", "white")
    index_html = f"""
    <html>
      <head>
        <title>Image Upload and Description</title>
      </head>
      <body style="background-color: {background_color};">
        <h2>Upload a JPEG Image</h2>
        <form method="post" enctype="multipart/form-data" action="/upload">
          <label>Choose file:</label>
          <input type="file" name="form_file" accept="image/jpeg"/>
          <button>Upload</button>
        </form>
        <hr>
        <h2>Uploaded Images</h2>
        <ul>
    """
    for file in list_blobs(BUCKET_NAME):
        json_file = file.rsplit('.', 1)[0] + ".json"
        index_html += f"<li><a href='/view/{file}'>{file}</a> | <a href='/files/{file}'>Download</a> | <a href='/json/{json_file}'>JSON</a></li>"
    index_html += "</ul></body></html>"
    return index_html

@app.route('/upload', methods=["POST"])
def upload():
    """Handles image upload, file storage, and Gemini AI caption generation."""
    file = request.files.get('form_file')
    if not file:
        return "<h3>Error: No file selected.</h3><a href='/'>Back to Upload</a>"

    filename = file.filename
    with tempfile.NamedTemporaryFile(delete=False) as temp_img:
        file.save(temp_img.name)
        upload_blob(BUCKET_NAME, temp_img.name, filename)

    metadata = generate_gemini_caption(temp_img.name)
    json_filename = filename.rsplit('.', 1)[0] + ".json"
    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp_json:
        json.dump(metadata, temp_json)
        temp_json.seek(0)
        upload_blob(BUCKET_NAME, temp_json.name, json_filename)

    return f"""
    <h2>Title: {metadata['title']}</h2>
    <p>Description: {metadata['description']}</p>
    <a href='/'>Back to Upload</a>
    """

@app.route('/files/<filename>')
def get_file(filename):
    """Fetches an image file from Google Cloud Storage for download."""
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    result = download_blob(BUCKET_NAME, filename, temp_file.name)
    if result:
        return send_file(temp_file.name, as_attachment=True)
    else:
        return "<h3>Error: File not found.</h3>", 404

@app.route('/json/<filename>')
def get_json_file(filename):
    """Fetches a JSON metadata file from Google Cloud Storage for download."""
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    result = download_blob(BUCKET_NAME, filename, temp_file.name)
    if result:
        return send_file(temp_file.name, as_attachment=True, mimetype="application/json")
    else:
        return jsonify({"error": "File not found"}), 404

@app.route('/view/<filename>')
def view_file(filename):
    """
    Displays the image along with its description by fetching the corresponding JSON metadata.
    The image is embedded from its public URL in Cloud Storage.
    """
    # Construct public URL for the image
    image_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
    # Build the JSON filename
    json_filename = filename.rsplit('.', 1)[0] + ".json"
    # Download the JSON file into a temporary file and load the metadata
    temp_json = tempfile.NamedTemporaryFile(delete=False)
    result = download_blob(BUCKET_NAME, json_filename, temp_json.name)
    if result:
        with open(temp_json.name, "r") as f:
            metadata = json.load(f)
    else:
        metadata = {"title": "No Title", "description": "No description available."}
    # Render an HTML page with the image and its description
    html = f"""
    <html>
      <head>
        <title>{metadata.get('title', 'Image')}</title>
      </head>
      <body>
        <h1>{metadata.get('title', 'Image')}</h1>
        <img src="{image_url}" alt="{metadata.get('title', 'Image')}" style="max-width:100%;">
        <p>{metadata.get('description', 'No description available.')}</p>
        <a href="/">Back to Upload</a>
      </body>
    </html>
    """
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)