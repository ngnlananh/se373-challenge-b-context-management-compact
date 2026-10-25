# Ghi chú công việc tuần 40 (dữ liệu giả cho lab)

## 2026-09-28: Endpoint đăng nhập
- Trạng thái: Hoàn thành
- Phụ trách: Lan
- Nội dung: Hoàn thành endpoint POST /auth/login, đã merge vào nhánh main, có unit test cho đăng nhập đúng và sai mật khẩu.

## 2026-09-29: Refresh token
- Trạng thái: Đang làm
- Phụ trách: Minh
- Nội dung: Đang implement refresh token rotation, xong khoảng 60%. Còn phần thu hồi refresh token cũ khi đăng xuất.

## 2026-09-30: Lỗi test OAuth
- Trạng thái: Chưa giải quyết
- Phụ trách: Hoa
- Nội dung: Test tích hợp đăng nhập OAuth với Google thất bại trên staging do redirect URI không khớp. Chưa xác định cấu hình nào sai.

## 2026-10-01: Tài liệu API đăng nhập cho mobile
- Trạng thái: Chưa bắt đầu
- Phụ trách: (chưa có người phụ trách)
- Nội dung: Team mobile cần tài liệu API đăng nhập và refresh token. Chưa có người nhận việc và chưa có deadline.

## 2026-10-02: Kế hoạch tuần tới
- Trạng thái: Kế hoạch
- Phụ trách: Cả nhóm
- Nội dung: Hoàn tất refresh token, tìm nguyên nhân lỗi OAuth trên staging, phân công người viết tài liệu API cho mobile.
