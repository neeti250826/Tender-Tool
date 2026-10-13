# Vietnam VNEPS / VNEPS (VN_VNEPS) — Advanced search

## Website
- Advanced search page (Contractor selection):
  - https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?render=search

## Advanced filters (as shown on the website)
On the advanced search page, the UI exposes (among others):

- Toggle filters
  - **Chỉ tìm kiếm các thông báo mời thầu chưa đóng thầu**
  - **Chỉ tìm kiếm các KHLCNT có gói thầu chưa đăng tải TBMT**

- Keyword input
  - **Nhập số TBMT/ Tên gói thầu**

- Entity filters
  - **Bên mời thầu**
  - **Chủ đầu tư**
  - **Nhà thầu trúng thầu**

- Dates + value ranges
  - **Ngày phê duyệt**
  - **Giá gói thầu (VND … VND)**
  - **Giá hợp đồng (VND … VND)**

- Classification / location
  - **Lĩnh vực**
  - **Địa điểm thực hiện**
  - **Loại công trình**
  - **Tên danh mục hàng hóa / dịch vụ**

- Procurement method filters
  - **Quy trình áp dụng**
  - **Hình thức LCNT**
  - **Phương thức LCNT**
  - **Trong nước/ Quốc tế**
  - **Hình thức dự thầu (Qua mạng / Không qua mạng)**

## Status of the scraper implementation
The scraper supports a **requests-based** listing fetch using the portal's `smart/search` JSON endpoint.
It uses **Playwright only to discover an ephemeral `token=` value** (unless you provide `--smart-token`).

### Quick start

```bash
python "Vietnam VNEPS/vneps_scraper.py" \
  --date-from 2026-01-01 \
  --date-to 2026-01-31 \
  --query "" \
  --tender-status open \
  --page-size 10 \
  --max-pages 3 \
  --output-target "./_local_outputs" \
  --project-name "MDT_2026" \
  --website-id "VN_VNEPS" \
  --source-label "Vietnam VNEPS" \
  --region "EMEA"
```

### Notes

- If Playwright is unavailable, you can still run requests-based paging by providing `--smart-token`.
- `--discover-only` remains available to capture general XHR/fetch traffic to `<outputs>/web/`.
