import Link from "next/link";

export default function NotFound() {
  return (
    <div className="panel">
      <h2>Không tìm thấy trang</h2>
      <p className="sub">Đường dẫn này không tồn tại hoặc đã bị xóa.</p>
      <Link href="/">Về Tổng quan</Link>
    </div>
  );
}
