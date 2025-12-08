# API Response Format - V-Tryon Backend V2

## POST /v2/tryon

### Request

```bash
curl -X POST http://localhost:8000/v2/tryon \
  -F "person_image=@person.jpg" \
  -F "garment_image=@garment.jpg"
```

### Success Response

**Status Code:** `200 OK`

**Content-Type:** `application/json`

**Response Body:**
```json
{
  "success": true,
  "image_url": "http://localhost:8000/media/tryon/2025/12/08/tryon_abc12345.png",
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

**Response Headers:**
```
X-RateLimit-Limit-Hourly: 10
X-RateLimit-Remaining-Hourly: 9
X-RateLimit-Limit-Daily: 40
X-RateLimit-Remaining-Daily: 39
```

### Error Responses

#### 400 Bad Request - Missing Files

```json
{
  "error": "person_image is required"
}
```

or

```json
{
  "error": "garment_image is required"
}
```

#### 429 Too Many Requests - Rate Limit Exceeded

```json
{
  "error": "Rate limit exceeded",
  "message": "You have exceeded the hourly rate limit of 10 requests per hour. Please try again later.",
  "rate_limit": {
    "type": "hourly",
    "limit": 10,
    "current": 11,
    "retry_after": "1 hour"
  }
}
```

#### 500 Internal Server Error

```json
{
  "error": "Internal server error while processing try-on request"
}
```

or

```json
{
  "error": "Failed to generate try-on image"
}
```

---

## Image Storage

### Storage Location

Generated images are saved to:
```
{MEDIA_ROOT}/tryon/YYYY/MM/DD/tryon_{uuid}.png
```

Example:
```
/media/azazul/PRS/projects/video_generation/gemini/v-tryon-v2/media/tryon/2025/12/08/tryon_abc12345.png
```

### URL Format

Images are accessible via:
```
{MEDIA_URL}tryon/YYYY/MM/DD/tryon_{uuid}.png
```

Example:
```
http://localhost:8000/media/tryon/2025/12/08/tryon_abc12345.png
```

### File Naming

- **Format:** `tryon_{8-character-uuid}.png`
- **Organization:** Date-based directory structure (YYYY/MM/DD)
- **Uniqueness:** UUID ensures no filename conflicts

### Accessing the Image

After receiving the response, you can:

1. **Use the URL directly:**
   ```javascript
   const response = await fetch('/v2/tryon', { ... });
   const data = await response.json();
   const imageUrl = data.image_url;
   // Use imageUrl in <img src={imageUrl} />
   ```

2. **Download the image:**
   ```bash
   curl http://localhost:8000/media/tryon/2025/12/08/tryon_abc12345.png --output result.png
   ```

---

## Example Usage

### JavaScript/TypeScript

```javascript
async function generateTryOn(personImageFile, garmentImageFile) {
  const formData = new FormData();
  formData.append('person_image', personImageFile);
  formData.append('garment_image', garmentImageFile);
  
  const response = await fetch('http://localhost:8000/v2/tryon', {
    method: 'POST',
    body: formData
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message || error.error);
  }
  
  const data = await response.json();
  return data.image_url; // Use this URL to display the image
}
```

### Python

```python
import requests

def generate_try_on(person_image_path, garment_image_path):
    url = 'http://localhost:8000/v2/tryon'
    
    with open(person_image_path, 'rb') as person, open(garment_image_path, 'rb') as garment:
        files = {
            'person_image': person,
            'garment_image': garment
        }
        
        response = requests.post(url, files=files)
        response.raise_for_status()
        
        data = response.json()
        return data['image_url']
```

---

## Notes

- Images are permanently stored on the server
- Images are organized by date for easy management
- Each image has a unique filename to prevent conflicts
- Images can be accessed directly via their URL
- In production, ensure Nginx is configured to serve `/media/` directory
- Consider implementing image cleanup/retention policies for production

