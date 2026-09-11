import { Archive, ArrowRight, BookOpen, Bot, Clock3, Database, FileText, Loader2, MessageSquare, Plus, Sparkles, Trash2 } from 'lucide-react';
import type { ResearchPaper, ResearchSpace } from './types';
import './research-home.css';

type ResearchHomeProps = {
  spaces: ResearchSpace[];
  onEnter: (spaceId: string) => void;
  onCreateSpace: () => void;
  onQuickChat: (spaceId: string) => void;
  onDelete: (space: ResearchSpace) => void;
  deletingSpaceId?: string;
  onOpenGlobalAssistant: () => void;
  resources: ResearchPaper[];
  onOpenResource: (resource: ResearchPaper) => void;
};

function formatDate(value?: string) {
  if (!value) return '刚刚更新';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '刚刚更新';
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

export default function ResearchHome({ spaces, onEnter, onCreateSpace, onQuickChat, onDelete, deletingSpaceId, onOpenGlobalAssistant, resources, onOpenResource }: ResearchHomeProps) {
  return (
    <main className="research-home">
      <header className="research-home-header">
        <div className="home-brand"><span className="home-mark">TF</span><span><strong>ThinkFlow</strong><small>Research spaces</small></span></div>
        <button className="primary-button home-create" onClick={onCreateSpace}><Plus size={16} />新建研究空间</button>
      </header>
      <section className="research-home-intro">
        <div className="home-kicker"><Sparkles size={15} />研究工作台</div>
        <h1>选择一个研究空间</h1>
        <p>把论文、Blog、讨论和研究想法放在同一个可持续的上下文里。</p>
      </section>
      <section className="global-assistant-entry" aria-label="全局研究助理">
        <span className="global-entry-icon"><Bot size={21} /></span>
        <span className="global-entry-copy"><strong>全局研究助理</strong><small>跨空间检索、规划研究方向，或批量把 title、DOI 和 arXiv 链接加入研究空间。</small></span>
        <span className="global-entry-capabilities"><span><Database size={13} />批量入库</span><span><MessageSquare size={13} />独立历史</span></span>
        <button onClick={onOpenGlobalAssistant}>打开助理<ArrowRight size={16} /></button>
      </section>
      <section className="home-resource-section" aria-label="全局资源库">
        <header className="home-section-header">
          <div><strong>全局资源库</strong><span>{resources.length} 项资源 · 可被多个研究空间复用</span></div>
          <span className="home-section-note"><Database size={14} />单份资源，多空间关联</span>
        </header>
        {resources.length ? <div className="home-resource-grid">
          {resources.slice(0, 6).map((resource) => {
            const isBlog = resource.resource_type === 'blog';
            const linkedSpaces = resource.space_ids?.length || 0;
            return <button className="home-resource-card" key={resource.id} onClick={() => onOpenResource(resource)}>
              <span className={`home-resource-icon ${isBlog ? 'blog' : 'paper'}`}>{isBlog ? <FileText size={16} /> : <BookOpen size={16} />}</span>
              <span className="home-resource-copy"><strong title={resource.title}>{resource.title}</strong><small>{isBlog ? 'Blog' : 'Paper'} · {linkedSpaces ? `${linkedSpaces} 个研究空间` : '尚未加入研究空间'}</small></span>
              <ArrowRight className="home-resource-arrow" size={16} />
            </button>;
          })}
        </div> : <div className="home-resource-empty"><Database size={18} /><span>资源导入后会出现在这里，可从多个研究空间复用。</span></div>}
      </section>
      {spaces.length ? (
        <section className="space-grid" aria-label="研究空间列表">
          {spaces.map((space) => (
            <article className="space-card" key={space.id}>
              <button className="space-card-main" onClick={() => onEnter(space.id)}>
                <span className="space-card-icon"><Archive size={19} /></span>
                <span className="space-card-copy"><strong>{space.title}</strong><small>{space.description || '还没有描述，进入空间开始整理研究材料。'}</small></span>
                <ArrowRight className="space-card-arrow" size={18} />
              </button>
              <footer className="space-card-footer">
                <span><Clock3 size={13} />{formatDate(space.updated_at)}</span>
                <span>{space.resource_count || 0} 个资源</span>
                <span><MessageSquare size={13} />{space.conversation_count || 0} 个对话</span>
                <span className="space-card-actions">
                  <button className="space-card-chat" onClick={() => onQuickChat(space.id)} disabled={Boolean(deletingSpaceId)} title="在此空间新建对话"><Plus size={14} />新对话</button>
                  <button
                    className="space-card-delete"
                    onClick={() => onDelete(space)}
                    disabled={Boolean(deletingSpaceId)}
                    title={`删除研究空间 ${space.title}`}
                    aria-label={`删除研究空间 ${space.title}`}
                  >
                    {deletingSpaceId === space.id ? <Loader2 className="spin" size={14} /> : <Trash2 size={14} />}
                  </button>
                </span>
              </footer>
            </article>
          ))}
        </section>
      ) : (
        <section className="home-empty">
          <Archive size={28} />
          <h2>还没有研究空间</h2>
          <p>例如创建“Software Engineering 的演进”，再把论文和 Blog 链接放进去。</p>
          <button className="primary-button" onClick={onCreateSpace}><Plus size={16} />创建第一个空间</button>
        </section>
      )}
    </main>
  );
}
