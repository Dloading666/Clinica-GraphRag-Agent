import { Tabs } from 'antd'
import TracePanel from './TracePanel'
import KnowledgeGraphPanel from './KnowledgeGraphPanel'
import SourcePanel from './SourcePanel'
import PerformancePanel from './PerformancePanel'
import ThinkingPanel from './ThinkingPanel'

const tabPanelStyle = {
  height: '100%',
  minHeight: 0,
} as const

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
      <style>{`
        .detail-tabs .ant-tabs-content-holder {
          flex: 1 1 auto;
          min-height: 0;
          overflow: hidden;
        }

        .detail-tabs .ant-tabs-content,
        .detail-tabs .ant-tabs-tabpane,
        .detail-tabs .ant-tabs-tabpane-active,
        .detail-tabs .detail-tab-scroll {
          height: 100%;
          min-height: 0;
        }

        .detail-tabs .detail-tab-scroll--scrollable {
          overflow-y: auto;
          overscroll-behavior: contain;
          -webkit-overflow-scrolling: touch;
        }
      `}</style>
      <Tabs
        className="detail-tabs"
        defaultActiveKey="thinking"
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
            key: 'thinking',
            label: '思考过程',
            children: (
              <div className="detail-tab-scroll" style={tabPanelStyle}>
                <ThinkingPanel />
              </div>
            ),
          },
          {
            key: 'trace',
            label: '执行轨迹',
            children: (
              <div className="detail-tab-scroll" style={tabPanelStyle}>
                <TracePanel />
              </div>
            ),
          },
          {
            key: 'kg',
            label: '知识图谱',
            children: (
              <div className="detail-tab-scroll" style={tabPanelStyle}>
                <KnowledgeGraphPanel />
              </div>
            ),
          },
          {
            key: 'source',
            label: '源内容',
            children: (
              <div
                className="detail-tab-scroll detail-tab-scroll--scrollable"
                style={tabPanelStyle}
              >
                <SourcePanel />
              </div>
            ),
          },
          {
            key: 'performance',
            label: '性能监控',
            children: (
              <div className="detail-tab-scroll" style={tabPanelStyle}>
                <PerformancePanel />
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
