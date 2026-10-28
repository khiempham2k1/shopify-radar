"use client";

import { useEffect, useState } from "react";
import { api, errorText, useApi } from "@/lib/api";
import { fmtDateTime, fmtNumber } from "@/lib/format";
import type { Edition, Item, ItemList, Source } from "@/lib/types";
import { AffectsSelect, PlatformRow } from "../ItemRows";
import { Empty, ErrorBox, Loading } from "../States";

const PAGE = 30;

function EditionCard({ e }: { e: Edition }) {
  const [s1, s2] = e.sections;
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{e.edition} Edition</h2>
        <a href={e.url} target="_blank" rel="noopener noreferrer" className="back">
          Mở trang Edition ↗
        </a>
      </div>
      <p className="sub">
        Tóm tắt do AI tách từ trang Editions{e.first_seen ? ` · thấy lần đầu ${fmtDateTime(e.first_seen)}` : ""}
        {e.unanalyzed > 0 ? ` · ${e.unanalyzed} tính năng chưa được AI phân loại` : ""}
      </p>
      <div className="edition">
        <div>
          <b>{fmtNumber(e.relevant)}</b>
          <span>tính năng liên quan theme (trên tổng {fmtNumber(e.total)})</span>
        </div>
        {s1 ? (
          <div>
            <b>{fmtNumber(s1.count)}</b>
            <span>thuộc nhóm {s1.section}</span>
          </div>
        ) : null}
        {s2 ? (
          <div>
            <b>{fmtNumber(s2.count)}</b>
            <span>thuộc nhóm {s2.section}</span>
          </div>
        ) : null}
      </div>
      {(e.sections.length > 2 || e.tags.length > 0) && (
        <div className="edition-tags">
          {e.sections.slice(2).map((s) => (
            <span key={s.section} className="tag">
              {s.section} · {s.count}
            </span>
          ))}
          {e.tags.length > 0 && <span>Tag:</span>}
          {e.tags.slice(0, 6).map((t) => (
            <span key={t.tag} className="tag">
              {t.tag} · {t.count}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function PlatformView() {
  const editions = useApi<Edition[]>("editions");
  const sources = useApi<Source[]>("sources");
  const [source, setSource] = useState("");
  const [edition, setEdition] = useState("");
  const [affects, setAffects] = useState("");
  const [allChanges, setAllChanges] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const query = (offset: number) => {
    const p = new URLSearchParams({ view: "platform", limit: String(PAGE), offset: String(offset) });
    if (source) p.set("source", source);
    if (edition) p.set("edition", edition);
    if (affects) p.set("affects", affects);
    if (allChanges) p.set("all_changes", "true");
    return `items?${p}`;
  };

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    const p = new URLSearchParams({ view: "platform", limit: String(PAGE), offset: "0" });
    if (source) p.set("source", source);
    if (edition) p.set("edition", edition);
    if (affects) p.set("affects", affects);
    if (allChanges) p.set("all_changes", "true");
    api<ItemList>(`items?${p}`, "GET", undefined, ctrl.signal)
      .then((d) => {
        setItems(d.items);
        setTotal(d.total);
        setLoading(false);
      })
      .catch((err) => {
        if ((err as Error).name === "AbortError") return;
        setError(errorText(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [source, edition, affects, allChanges, tick]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const d = await api<ItemList>(query(items.length));
      setItems((prev) => [...prev, ...d.items.filter((i) => !prev.some((p) => p.id === i.id))]);
      setTotal(d.total);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoadingMore(false);
    }
  }

  function pickSource(id: string) {
    setSource(id);
    setEdition("");
  }

  const platformSources = (sources.data ?? []).filter((s) => s.kind === "platform" && s.enabled);
  // Edition cards and the per-Edition filter only make sense on the Shopify Editions tab.
  const editionSource = platformSources.find((s) => s.type === "editions");
  const onEditions = !!editionSource && source === editionSource.id;
  const editionList = editions.data ?? [];
  const shownEditions = edition ? editionList.filter((e) => e.edition === edition) : editionList.slice(0, 2);
  const sourceName = platformSources.find((s) => s.id === source)?.name;

  return (
    <>
      <div className="top">
        <div>
          <h1>Thay đổi nền tảng</h1>
          <p>Dev changelog, Shopify Changelog, Shopify Editions và GitHub releases trên cùng một timeline.</p>
        </div>
      </div>

      {onEditions && editions.error && <ErrorBox error={editions.error} onRetry={() => editions.reload()} prefix="Không tải được tóm tắt Editions" />}
      {onEditions && shownEditions.map((e) => <EditionCard key={e.edition} e={e} />)}

      <div className="filters" role="group" aria-label="Bộ lọc">
        <button type="button" className="chip" aria-pressed={source === ""} onClick={() => pickSource("")}>
          Tất cả
        </button>
        {platformSources.map((s) => (
          <button key={s.id} type="button" className="chip" aria-pressed={source === s.id} onClick={() => pickSource(s.id)}>
            {s.name}
          </button>
        ))}
        {sources.error && <span className="muted">Không tải được danh sách nguồn.</span>}
        <span className="spacer" />
        <label className="check" title="Thay đổi chính thức mà AI xếp là không liên quan theme vẫn được lưu; bật để xem cả chúng">
          <input type="checkbox" checked={allChanges} onChange={(e) => setAllChanges(e.target.checked)} /> Hiện cả thay đổi AI cho là không liên quan theme
        </label>
        <AffectsSelect value={affects} onChange={setAffects} />
      </div>

      {onEditions && editionList.length > 0 && (
        <div className="filters" role="group" aria-label="Lọc theo Edition">
          <button type="button" className="chip" aria-pressed={edition === ""} onClick={() => setEdition("")}>
            Tất cả Edition
          </button>
          {editionList.map((e) => (
            <button key={e.edition} type="button" className="chip" aria-pressed={edition === e.edition} onClick={() => setEdition(e.edition)}>
              {e.edition}
            </button>
          ))}
        </div>
      )}

      <div className="panel">
        {error && <ErrorBox error={error} onRetry={() => setTick((t) => t + 1)} />}
        {loading ? (
          <Loading />
        ) : !error && items.length === 0 ? (
          <Empty>
            {edition
              ? `Không có tính năng nào của ${edition} khớp bộ lọc.`
              : affects
              ? "Không có thay đổi nào khớp bộ lọc trong 60 ngày qua."
              : sourceName
                ? `Không có thay đổi nào từ ${sourceName} trong 60 ngày qua.`
                : "Chưa có thay đổi nền tảng nào trong 60 ngày qua."}
          </Empty>
        ) : (
          <div className="list">
            {items.map((item) => (
              <PlatformRow key={item.id} item={item} />
            ))}
          </div>
        )}
        {!loading && items.length > 0 && (
          <div className="more">
            <span>
              Đang hiện {fmtNumber(items.length)} / {fmtNumber(total)} thay đổi
            </span>
            {items.length < total && (
              <button type="button" className="btn" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Đang tải…" : "Tải thêm"}
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
}
