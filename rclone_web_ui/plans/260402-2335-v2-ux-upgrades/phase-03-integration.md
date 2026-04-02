# Phase 03: Integration & Testing
Status: ⬜ Pending

## Objective
Tie the frontend logic in `app.js` to the new DOM elements and the new backend APIs. Ensure flawless data flow.

## Implementation Steps
1. [ ] **Smart Source**: When a job is submitted, if a URL involves `drive.google.com`, extract the ID locally. If "Wrap in Parent Folder" is checked, ping `/api/util/scrape_title` to get the real folder name, wait for the response, construct `{dest}/{FolderName}`, and append to the job.
2. [ ] **Destination Dropdown**: Whenever a job is submitted, save the destination value and an optional human-readable name into Javascript `localStorage`. Populate dropdown logic when focusing on the destination input.
3. [ ] **Explorer Modal Logic**: Wire open/close events. When opened for the first time, fetch `/api/explore?path=gc:`. clicking folders triggers recursive refetches. Provide breadcrumbs mechanism. "Create" prompts for a name and hits `/api/mkdir`. "Select" populates the Destination input.
4. [ ] **Auth Modal**: JS triple-click detection. On 3 clicks, pop `prompt()`. Check with `/api/auth`. If valid, show Config tab. Ensure `/api/config` saves check for password (or auth token).

## Files to Modify
- `static/js/app.js`
