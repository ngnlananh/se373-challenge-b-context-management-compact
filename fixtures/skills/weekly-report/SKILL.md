---
name: weekly-report
description: Tạo báo cáo tiến độ tuần từ file ghi chú công việc trong workspace (ví dụ data/weekly_notes.md) và lưu thành file Markdown dưới output/. Dùng khi người dùng yêu cầu báo cáo tuần, tổng hợp tiến độ tuần hoặc weekly report.
---

# Weekly report

Hướng dẫn tạo báo cáo tuần từ ghi chú công việc.

## Các bước

1. Đọc file nguồn người dùng chỉ định bằng `read_file` (mặc định `data/weekly_notes.md`). Nếu đọc lỗi, báo lỗi và dừng; không tự tạo nội dung.
2. Đọc template `references/report-template.md` trong thư mục skill này, tức `skills/weekly-report/references/report-template.md`.
3. Phân loại từng ghi chú theo đúng trạng thái ghi trong nguồn:
   - `Hoàn thành` → **Đã hoàn thành**.
   - `Đang làm` → **Đang thực hiện**, giữ tiến độ nếu nguồn có ghi (ví dụ 60%).
   - `Chưa giải quyết`, `Bị chặn` hoặc mô tả lỗi chưa xử lý → **Vướng mắc**.
   - `Kế hoạch` → **Kế hoạch tiếp theo**.
   - Việc `Chưa bắt đầu` đưa vào mục phù hợp nhất (thường là Kế hoạch tiếp theo) và nêu rõ chưa bắt đầu.
4. Không chuyển việc chưa xong thành hoàn thành. Không thêm việc, ngày hay người phụ trách không có trong nguồn.
5. Mục **Thông tin cần bổ sung**: liệt kê dữ liệu thiếu thấy trong nguồn, ví dụ việc chưa có người phụ trách, chưa có deadline, lỗi chưa rõ nguyên nhân. Nếu không thiếu gì, ghi "Không có".
6. Điền đúng các mục của template, ghi ngày nguồn khi có. Ghi file bằng `write_file` vào đường dẫn người dùng yêu cầu (mặc định `output/weekly-report.md`).
7. Trả lời người dùng: đường dẫn file đã ghi (theo kết quả `write_file`) và tóm tắt 2–3 dòng. Nếu ghi lỗi, báo lỗi.
