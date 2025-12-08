# V-Tryon Backend V2

A Django REST API backend for virtual try-on functionality using Google Vertex AI.

## Setup

### 1. Conda Environment

The project uses a conda environment named `v-tryon-v2`. To activate it:

```bash
conda activate v-tryon-v2
```

### 2. Environment Variables

Copy the example environment file and configure it:

```bash
cp .env.example .env
```

Edit `.env` and set the following required variables:

- `GOOGLE_CLOUD_PROJECT`: Your Google Cloud project ID
- `GOOGLE_CLOUD_LOCATION`: Google Cloud location (default: us-central1)
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to your service account JSON key file (for production)
- `GOOGLE_GENAI_USE_VERTEXAI`: Set to `true` to use Vertex AI

### 3. Google Cloud Authentication

For local development:
```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

For production deployment, use a service account JSON key file and set `GOOGLE_APPLICATION_CREDENTIALS` environment variable.

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Run Migrations

```bash
python manage.py migrate
```

### 6. Run Development Server

```bash
python manage.py runserver
```

## API Endpoints

### POST /v2/tryon

Virtual try-on endpoint that accepts two image files and returns a generated image.

**Request:**
- Method: POST
- Content-Type: multipart/form-data
- Parameters:
  - `person_image`: Image file of the person
  - `garment_image`: Image file of the garment

**Response:**
- Content-Type: application/json
- Body: JSON object with image URL
  ```json
  {
    "success": true,
    "image_url": "http://localhost:8000/media/tryon/2025/12/08/tryon_abc123.png",
    "message": "Try-on image generated successfully",
    "rate_limit": {
      "hourly": {
        "limit": 10,
        "remaining": 9,
        "used": 1
      },
      "daily": {
        "limit": 40,
        "remaining": 39,
        "used": 1
      }
    }
  }
  ```

**Note:** The generated image is saved to the server's media directory and can be accessed via the returned URL. Images are organized by date: `media/tryon/YYYY/MM/DD/tryon_{uuid}.png`

**Rate Limits:**
- 10 requests per hour per IP
- 40 requests per day per IP
- Rate limits are tracked per unique IP address
- Rate limit status is included in response headers
- See [RATE_LIMITING.md](RATE_LIMITING.md) for detailed documentation

**Authentication:**
- No authentication required - this is a public API
- Rate limiting is the only restriction mechanism

**Rate Limit Management:**
- Check rate limit status: `python manage.py ratelimit status <ip_address>`
- Reset rate limit: `python manage.py ratelimit reset <ip_address>`

**Example using curl:**
```bash
# Make request and get JSON response with image URL
curl -X POST http://localhost:8000/v2/tryon \
  -F "person_image=@person.jpg" \
  -F "garment_image=@garment.jpg"

# Response:
# {
#   "success": true,
#   "image_url": "http://localhost:8000/media/tryon/2025/12/08/tryon_abc123.png",
#   "message": "Try-on image generated successfully",
#   ...
# }

# Then access the image directly:
curl http://localhost:8000/media/tryon/2025/12/08/tryon_abc123.png --output result.png
```

## Project Structure

```
v-tryon-v2/
├── v_tryon_backend_v2/     # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── tryon/                   # Try-on app
│   ├── views.py            # API views
│   ├── urls.py             # URL routing
│   └── services/           # Business logic
│       └── vertex_tryon.py # Vertex AI service
├── version_control/         # Version control app
│   ├── models.py           # AppVersion model
│   ├── views.py            # Version check API
│   └── urls.py             # Version URLs
├── requirements.txt
├── .env
├── .env.example
├── gunicorn_config.py      # Gunicorn configuration
├── DEPLOYMENT.md           # Complete deployment guide
├── IMAGE_UPLOAD_CONFIGURATION.md  # Image upload size guide
├── RATE_LIMITING.md        # Rate limiting documentation
└── manage.py
```

## Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Complete production deployment guide with Gunicorn
- **[IMAGE_UPLOAD_CONFIGURATION.md](IMAGE_UPLOAD_CONFIGURATION.md)** - Guide for configuring image upload size limits
- **[RATE_LIMITING.md](RATE_LIMITING.md)** - Rate limiting documentation
- **[version_control/README.md](version_control/README.md)** - Version control API documentation

## Requirements

- Python 3.11
- Django 5.2.9
- Google Cloud Vertex AI access
- Application Default Credentials or Service Account

## Notes

- The API does not store any data - it processes images and returns results
- Temporary files are automatically cleaned up after processing
- Structured logging is used throughout the application for debugging

