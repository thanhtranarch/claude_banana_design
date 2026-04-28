# Claude Banana Design — Project Settings

## /banana Default Configuration

- **Aspect ratio:** `3:2` (tất cả ảnh generate đều dùng 3:2, trừ khi user chỉ định khác)
- **Resolution:** `2K` → fallback `1K` → fallback `512` nếu bị rate limit theo phút (RPM)
- **Model:** `gemini-3.1-flash-image-preview`

## Fallback Resolution Policy

Khi bị lỗi rate limit (429 RPM), tự động thử lại với resolution thấp hơn:
1. Thử `2K` trước
2. Nếu thất bại do RPM → thử `1K`
3. Nếu vẫn thất bại → thử `512`

**Lưu ý:** Nếu lỗi là daily quota (`GenerateRequestsPerDayPerProjectPerModel`), resolution thấp hơn KHÔNG giúp được — cần API key mới hoặc bật billing.
