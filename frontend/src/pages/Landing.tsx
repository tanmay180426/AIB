import { Link } from 'react-router-dom'
import { Brand } from '@/components/ui/Workspace'
import { Icon } from '@/components/ui/Icon'

const features = [
  { icon: 'data', title: 'A home for your data', body: 'Upload structured files or CSV bundles. Inspect schemas, confirm mappings, and keep every table in its own private dataset context.' },
  { icon: 'chart', title: 'Evidence in every view', body: 'Explore observed metrics, shared filters, and data quality. Export the same scoped results you see in your workspace.' },
  { icon: 'model', title: 'Intelligence with context', body: 'Use computed numerical Insights and compatible saved ML models. Optional local language generation adds explanations when available.' },
]

export default function Landing() {
  return <div className="abi-landing">
    <nav className="abi-landing-nav" aria-label="Public navigation"><Brand /><Link className="abi-button" to="/login">Open workspace <Icon name="arrow" size={15} /></Link></nav>
    <main>
      <section className="abi-landing-hero">
        <div><div className="abi-eyebrow">Autonomous Business Intelligence / ABI</div><h1>AI-Powered Business Intelligence.<br /><span>Built around your data.</span></h1><p>One connected workspace for analytics, predictive models, and clear decisions. Bring your own datasets. Keep the evidence in view.</p><Link className="abi-button abi-button-primary mt-8" to="/login">Sign in to open the dashboard <Icon name="arrow" size={15} /></Link><div className="mt-6 abi-eyebrow">Local computation. Private datasets. No required paid API.</div></div>
        <div className="abi-landing-flow" aria-label="Platform workflow">
          <p className="abi-eyebrow mb-5">From source to understanding</p>
          <div className="abi-flow-node"><Icon name="data" /><div><strong>Your datasets</strong><small>Files, folders &amp; CSV bundles</small></div></div><div className="abi-flow-line" />
          <div className="abi-flow-node"><Icon name="filter" /><div><strong>A shared context</strong><small>Validated fields, relationships &amp; filters</small></div></div><div className="abi-flow-line" />
          <div className="abi-flow-node" style={{ borderColor: 'rgb(var(--primary) / .4)' }}><Icon name="chart" /><div><strong>Decisions grounded in evidence</strong><small>Analytics, reports &amp; compatible models</small></div></div>
        </div>
      </section>
      <section className="abi-landing-features" aria-label="Platform capabilities">{features.map((feature, index) => <article key={feature.title}><span className="abi-eyebrow">0{index + 1} / <Icon name={feature.icon} style={{ display: 'inline', marginLeft: 8 }} /></span><h2>{feature.title}</h2><p>{feature.body}</p></article>)}</section>
    </main>
    <footer className="abi-landing-footer"><span>ABI / AUTONOMOUS BUSINESS INTELLIGENCE</span><span>Trained inference requires compatible, separately installed artifacts.</span></footer>
  </div>
}
