# Version Control App

This Django app manages app version control for mobile applications. It allows the backend to enforce version requirements and force app updates when necessary.

## Features

- **Version Management**: Store and manage app versions with semantic versioning
- **Force Update**: Option to force all users to update to the latest version
- **Minimum Version**: Set minimum required version that apps must meet
- **Version Comparison**: Automatically compare app versions and determine if update is required
- **Admin Interface**: Easy-to-use Django admin interface for managing versions

## API Endpoint

### GET `/v2/current-version`

Get current app version information and check if app needs to update.

#### Query Parameters

- `app_version` (optional): The current app version (e.g., '1.0.0')
  - If provided, the API will compare and return whether update is required
  - If not provided, returns current version information only

#### Example Request

```bash
# Check version without comparing
curl http://localhost:8000/v2/current-version

# Check if app version 1.0.0 needs update
curl http://localhost:8000/v2/current-version?app_version=1.0.0
```

#### Example Response (Update Required)

```json
{
    "current_version": "1.2.0",
    "minimum_required_version": "1.1.0",
    "force_update": false,
    "is_valid": false,
    "requires_update": true,
    "is_blocked": true,
    "message": "App version 1.0.0 is no longer supported. Please update to version 1.1.0 or higher.",
    "update_url": "https://play.google.com/store/apps/details?id=com.example.app",
    "release_notes": "Bug fixes and performance improvements"
}
```

#### Example Response (Version Valid)

```json
{
    "current_version": "1.2.0",
    "minimum_required_version": "1.1.0",
    "force_update": false,
    "is_valid": true,
    "requires_update": false,
    "is_blocked": false,
    "message": "App version is up to date.",
    "update_url": "",
    "release_notes": "Bug fixes and performance improvements"
}
```

## Model: AppVersion

### Fields

- `version_number`: Current app version (e.g., '1.0.0', '1.2.3')
- `minimum_required_version`: Minimum version required to use the app
- `force_update`: If True, all apps must update (blocks all versions below current)
- `is_active`: If False, this version configuration is disabled
- `release_date`: When this version was released
- `release_notes`: Release notes or changelog
- `update_url`: URL where users can download/update the app
- `update_message`: Message shown to users when update is required

### Methods

- `get_current_version()`: Class method to get the currently active version
- `compare_version(app_version)`: Compare app version and return validation status

## Admin Interface

Access the admin interface at `/admin/` to manage app versions:

1. **Create New Version**: Add a new version configuration
2. **Set Minimum Version**: Define the minimum required version
3. **Enable Force Update**: Force all users to update
4. **Manage Active Versions**: Activate/deactivate version configurations

## Usage in Mobile App

### Recommended Flow

1. **On App Launch**: Check version on app startup
2. **Compare Versions**: Send current app version to API
3. **Handle Response**:
   - If `is_blocked == true`: Show update dialog and block app usage
   - If `requires_update == true`: Show optional update prompt
   - If `is_valid == true`: Allow app to continue

### Example Implementation (Pseudo-code)

```javascript
async function checkAppVersion() {
    const appVersion = getAppVersion(); // e.g., "1.0.0"
    const response = await fetch(`/v2/current-version?app_version=${appVersion}`);
    const data = await response.json();
    
    if (data.is_blocked) {
        // Force update - block app usage
        showUpdateDialog({
            message: data.message,
            updateUrl: data.update_url,
            forceUpdate: true
        });
        return false; // Block app
    } else if (data.requires_update) {
        // Optional update
        showUpdateDialog({
            message: data.message,
            updateUrl: data.update_url,
            forceUpdate: false
        });
    }
    
    return true; // Allow app to continue
}
```

## Version Comparison Logic

The system uses semantic versioning (major.minor.patch):

- **Version Format**: `major.minor.patch` (e.g., 1.2.3)
- **Comparison**: Numeric comparison of version parts
- **Minimum Version Check**: App version must be >= minimum_required_version
- **Force Update Check**: If force_update is True, app version must be >= current_version

## Best Practices

1. **Version Naming**: Use semantic versioning (e.g., 1.0.0, 1.1.0, 2.0.0)
2. **Gradual Rollout**: Start with `force_update=False` to allow gradual adoption
3. **Clear Messages**: Provide clear update messages explaining why update is needed
4. **Update URLs**: Always provide valid update URLs (App Store, Play Store)
5. **Testing**: Test version comparison before deploying to production

## Migration

To create the database tables:

```bash
python manage.py makemigrations version_control
python manage.py migrate
```

## Initial Setup

After migration, create an initial version in Django admin:

1. Go to `/admin/version_control/appversion/add/`
2. Set:
   - Version Number: `1.0.0`
   - Minimum Required Version: `1.0.0`
   - Force Update: `False`
   - Is Active: `True`
   - Release Notes: `Initial version`

Or use Django shell:

```python
from version_control.models import AppVersion

AppVersion.objects.create(
    version_number='1.0.0',
    minimum_required_version='1.0.0',
    force_update=False,
    is_active=True,
    release_notes='Initial version'
)
```

