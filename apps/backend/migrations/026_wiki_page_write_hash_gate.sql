-- Wiki 页面写入哈希门禁：在预览/确认时固化目标页哈希，
-- 应用时若外部修改导致哈希不匹配则停止写入并返回冲突。
ALTER TABLE wiki_workflow_page_updates ADD COLUMN target_content_hash TEXT;
