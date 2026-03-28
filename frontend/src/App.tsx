import { useEffect } from 'react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { api } from './api'
import { useConfigStore } from './stores/configStore'
import MainLayout from './components/Layout/MainLayout'

export default function App() {
  const setConfig = useConfigStore((s) => s.setConfig)

  useEffect(() => {
    api
      .getConfig()
      .then((res) => setConfig(res.data))
      .catch(console.error)
  }, [setConfig])

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      <MainLayout />
    </ConfigProvider>
  )
}
