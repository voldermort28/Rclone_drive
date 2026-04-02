# Specification: GDriveDL Version 2.0 UX Upgrades

## 1. Executive Summary
The V2 updates aim to dramatically improve the user quality-of-life on the Web UI. It solves the friction of manually extracting Google Drive folder IDs, manually finding the original name, and resolving duplicate structures. It also secures the platform configuration and introduces a fully-fledged visual Drive Explorer.

## 2. User Stories
- **Smart Transfer**: As a user, I want to paste raw Google Drive URLs so that I don't have to manually slice strings to get the `gc:{id}` format. I also want the system to automatically retrieve the remote folder name and nest my downloaded files properly.
- **Drive Browser**: As a user, I want to visually browse the folders on my Destination Drive from the web UI so I don't have to guess the correct ID or manually type new names.
- **Security Check**: As a system administrator, I want the Configuration/Service Account sections hidden by default and protected by a password so unauthorized guests cannot extract my credentials.

## 3. API Contract additions

`GET /api/util/scrape_title`
- **Query Params**: `url`
- **Response**: `{"title": "The folder name"}`

`GET /api/explore`
- **Query Params**: `path` (e.g. `gc:` or `gc:1234abcd`)
- **Response**: Array of rclone items. `[{"Path": "...", "Name": "...", "ID": "...", "IsDir": true}]`

`POST /api/mkdir`
- **Body**: `{"path": "gc:1234abcd/New_Folder_Name"}`
- **Response**: `{"success": true}`

`POST /api/auth`
- **Body**: `{"password": "secret_password"}`
- **Response**: `{"success": true, "token": "..."}` or `{"success": false}`

## 4. UI Components

- **Explorer Modal**: Floating HTML overlay initialized closed. Contains a breadcrumb div, a list of clickable `.flex` rows (representing folders), and inputs to create new folders on the fly.
- **Destination Dropdown**: HTML `<datalist>` or custom absolute-positioned `div` to show local storage history strings.
- **Smart Wrapper Checkbox**: A simple HTML `<input type="checkbox">` rendered under the Source textarea.

## 5. Security Logic
When the page loads, CSS class `.hidden` is applied to `#tab-config`.
An EventListener attaches a click counter to the `#header-logo`. On counter == 3, `prompt()` appears. If validated against `app.py`, remove `.hidden` from the config tab. Server-side validations will be added to the config file saves.
