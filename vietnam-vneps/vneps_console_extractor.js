/* ============================================================================
 * VNEPS Awarded Medtech Extractor  —  run in your OWN Chrome (not automation)
 * ----------------------------------------------------------------------------
 * HOW TO USE
 *   1. Open  https://muasamcong.mpi.gov.vn/en/web/guest/winning-bid-data
 *      (Look up -> "Cơ sở dữ liệu về đơn giá trúng thầu").  Stay signed OUT is fine.
 *   2. Press F12 -> Console tab.
 *   3. Paste this whole file, press Enter.  Wait until it prints "DONE".
 *   4. It auto-downloads  vneps_awarded_medtech.csv  to your Downloads folder.
 *   5. Tell Claude the file is in Downloads; it will map + merge it.
 *
 * It hits the same guest search API the page itself uses
 *   POST /o/egp-portal-winning-bid-data/services/smart/search_prc
 * category tab = THIET_BI_VAT_TU_Y_TE (Medical equipment & supplies).
 * ==========================================================================*/
(async () => {
  // Medtronic-taxonomy-relevant Vietnamese/English device keywords.
  // De-duplicated by record id, so re-running the whole list is safe.
  const KEYWORDS = [
    // --- Original set (v1) ---
    "stent", "van tim", "vòng van", "máy tạo nhịp", "máy phá rung", "điện cực",
    "catheter đốt", "ống thông đốt", "lưới thoát vị", "nẹp khóa", "đinh nội tủy",
    "khớp háng", "khớp gối", "nội khí quản", "mở khí quản", "trocar", "oxygenator",
    "màng trao đổi oxy", "bóng nong", "nút mạch", "ghim khâu", "dao siêu âm",
    "ống nội soi", "guide wire", "vòng xoắn", "coil nút mạch", "máy khâu nối",
    "van động mạch chủ", "dây dẫn can thiệp",

    // --- Coronary & Renal Denervation (CRDN) ---
    "ống thông dẫn đường", "vi ống thông", "ống thông chẩn đoán", "bóng phủ thuốc",
    "khoan cắt mảng xơ vữa", "dây dẫn áp lực", "siêu âm nội mạch",
    // --- Cardiac Rhythm Management (CRM) ---
    "điện cực tạo nhịp", "máy khử rung", "máy ghi điện tim cấy",
    // --- Structural Heart & Aortic ---
    "dù bít", "van động mạch phổi", "ống ghép nội mạch", "ống ghép mạch máu",
    // --- Peripheral & Endovenous / PVH ---
    "laser nội tĩnh mạch", "suy giãn tĩnh mạch", "sóng cao tần tĩnh mạch",
    "lọc tĩnh mạch chủ", "nút mạch ngoại vi", "khoan xơ vữa",
    // --- Neurovascular (NV) ---
    "stent chuyển dòng", "ống hút huyết khối", "dụng cụ lấy huyết khối",
    "keo nút mạch", "bóng chẹn",
    // --- Surgical Innovations (SI) ---
    "chỉ khâu", "dao điện", "dao hàn mạch", "clip phẫu thuật", "vật liệu cầm máu",
    "máy cắt nối",
    // --- Endoscopy ---
    "viên nang nội soi", "clip cầm máu", "thòng lọng", "kim tiêm cầm máu",
    "ống nong đường mật",
    // --- Ear Nose Throat (ENT) ---
    "nội soi tai mũi họng", "bóng nong xoang", "dao bào",
    // --- Acute Care & Monitoring (ACM) ---
    "cảm biến spo2", "chăn sưởi",
    // --- Cranial & Spinal Technologies (CST) ---
    "vít cột sống", "lồng liên thân đốt", "nẹp cột sống", "van dẫn lưu não thất",
    "dẫn lưu não thất", "nẹp sọ",
    // --- Neuromodulation / Pelvic Health ---
    "kích thích tủy sống", "kích thích não sâu", "kích thích thần kinh cùng",
    // --- Diabetes ---
    "bơm insulin", "cảm biến đường huyết",
    // --- Surgical Robotics ---
    "robot phẫu thuật",
    // --- Urology (bonus, near-adjacent) ---
    "ống thông JJ", "máy tán sỏi"
  ];
  const URL = "/o/egp-portal-winning-bid-data/services/smart/search_prc";
  const bodyFor = (kw, page) => ([{ pageSize: 100, pageNumber: page, query: [{
    index: "es-smart-pricing", keyWord: kw, keyWordNotMatch: "", matchType: "all-1",
    matchFields: ["ten_thiet_bi","ma_hs","xuat_xu","ma_tbmt","ky_ma_hieu","nhan_hieu","hang_san_xuat"],
    filters: [{ fieldName: "type", searchType: "in", fieldValues: ["HANG_HOA"] },
              { fieldName: "tab",  searchType: "in", fieldValues: ["THIET_BI_VAT_TU_Y_TE"] }] }] }]);

  const all = new Map();
  for (const kw of KEYWORDS) {
    let page = 0, total = null;
    while (true) {
      let r;
      try {
        r = await fetch(URL, { method: "POST",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(bodyFor(kw, page)) });
      } catch (e) { console.warn(kw, "fetch error", e); break; }
      if (!r.ok) break;
      const j = await r.json();
      const pg = (Array.isArray(j) ? j[0] : j).page || {};
      total = pg.totalElements;
      const list = pg.content || [];
      if (!list.length) break;
      for (const x of list) {
        if (!all.has(x.id)) all.set(x.id, {
          keyword: kw, name: x.tenThietBi, unit: x.donViTinh, quantity: x.khoiLuongDouble,
          origin: x.xuatXu, hs_code: x.maHs, product_code: x.chungLoai, brand: x.nhanHieu,
          manufacturer: x.hangSanXuat, model: x.kyMaHieu, license_no: x.soLuuHanh,
          year: x.namSanXuat, unit_price: x.donGia, notice_no: x.maTbmt,
          buyer: x.tenCdtBmt, bid_form: x.bidForm, result_date: x.ngayDangTaiKqlcnt,
          decision_no: x.soQuyetDinh, decision_date: x.ngayBanHanhQuyetDinh,
          supplier: x.winningName, num_contractors: x.soNhaThauThamDu, location: x.diaDiem
        });
      }
      page++;
      if (page >= (pg.totalPages || 0)) break;
      await new Promise(res => setTimeout(res, 80));   // be polite to the server
    }
    console.log(`${kw}: total=${total}, collected so far=${all.size}`);
  }

  // -> CSV
  const rows = [...all.values()];
  const cols = Object.keys(rows[0] || { name: 1 });
  const esc = v => { v = (v == null ? "" : String(v)).replace(/"/g, '""'); return `"${v}"`; };
  const csv = "﻿" + cols.join(",") + "\n" + rows.map(r => cols.map(c => esc(r[c])).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL ? URL.createObjectURL(blob) : window.URL.createObjectURL(blob);
  a.href = window.URL.createObjectURL(blob);
  a.download = "vneps_awarded_medtech.csv";
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`DONE — downloaded vneps_awarded_medtech.csv with ${rows.length} awarded items.`);
})();
