import { Tabs } from 'antd'
import TracePanel from './TracePanel'
import KnowledgeGraphPanel from './KnowledgeGraphPanel'
import SourcePanel from './SourcePanel'
import PerformancePanel from './PerformancePanel'

export default function DetailPanel() {
  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <Tabs
        className="detail-tabs"
        defaultActiveKey="trace"
        size="small"
        style={{
          flex: 1,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
        tabBarStyle={{
          padding: '0 8px',
          marginBottom: 0,
          background: '#fafafa',
          borderBottom: '1px solid #f0f0f0',
          flexShrink: 0,
        }}
        items={[
          {
            key: 'trace',
            label: '执行轨迹',
            children: (
              <div className="detail-tab-scroll" style={{ height: '100%' }}>
                <TracePanel />
              </div>
            ),
          },
          {
            key: 'kg',
            label: '知识图谱',
            children: (
              <div className="detail-tab-scroll" style={{ height: '100%' }}>
                <KnowledgeGraphPanel />
              </div>
            ),
          },
          {
            key: 'source',
            label: '源内容',
            children: (
              <div className="detail-tab-scroll" style={{ height: '100%' }}>
                <SourcePanel />
              </div>
            ),
          },
          {
            key: 'performance',
            label: '性能监控',
            children: (
              <div className="detail-tab-scroll" style={{ height: '100%' }}>
                <PerformancePanel />
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
