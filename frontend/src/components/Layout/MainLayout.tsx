import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import {
  AppstoreOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import {
  Avatar,
  Button,
  Drawer,
  Layout,
  Space,
  Tooltip,
  Typography,
  message,
} from 'antd'
import ChatPanel from '../Chat/ChatPanel'
import DetailPanel from '../Detail/DetailPanel'
import Sidebar from '../Sidebar/Sidebar'
import { useProfileStore } from '../../stores/profileStore'

const { Header, Content, Sider } = Layout

const MAX_AVATAR_FILE_SIZE = 5 * 1024 * 1024
const AVATAR_OUTPUT_SIZE = 256
const MOBILE_BREAKPOINT = 960

function useIsMobile() {
  const getMatches = () =>
    typeof window !== 'undefined' && window.innerWidth <= MOBILE_BREAKPOINT
  const [isMobile, setIsMobile] = useState(getMatches)

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    const mediaQuery = window.matchMedia(
      `(max-width: ${MOBILE_BREAKPOINT}px)`
    )
    const handleChange = (event?: MediaQueryListEvent) => {
      setIsMobile(event ? event.matches : mediaQuery.matches)
    }

    handleChange()

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleChange)
      return () => mediaQuery.removeEventListener('change', handleChange)
    }

    mediaQuery.addListener(handleChange)
    return () => mediaQuery.removeListener(handleChange)
  }, [])

  return isMobile
}

export default function MainLayout() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const isMobile = useIsMobile()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const avatarDataUrl = useProfileStore((s) => s.avatarDataUrl)
  const setAvatarDataUrl = useProfileStore((s) => s.setAvatarDataUrl)

  const openAvatarPicker = () => {
    fileInputRef.current?.click()
  }

  const handleAvatarChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''

    if (!file) return

    if (!file.type.startsWith('image/')) {
      message.warning('请选择图片文件作为头像。')
      return
    }

    if (file.size > MAX_AVATAR_FILE_SIZE) {
      message.warning('头像图片请控制在 5MB 以内。')
      return
    }

    try {
      const nextAvatarDataUrl = await convertImageToAvatarDataUrl(file)
      setAvatarDataUrl(nextAvatarDataUrl)
      message.success('头像已更新。')
    } catch (error) {
      console.error(error)
      message.error('头像上传失败，请换一张图片重试。')
    }
  }

  const renderAvatarPicker = () => (
    <>
      <Tooltip title="点击更换头像">
        <Avatar
          src={avatarDataUrl ?? undefined}
          icon={!avatarDataUrl ? <UserOutlined /> : undefined}
          style={{
            background: '#1677ff',
            cursor: 'pointer',
            border: '2px solid rgba(22,119,255,0.12)',
          }}
          size={isMobile ? 30 : 32}
          onClick={openAvatarPicker}
        />
      </Tooltip>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleAvatarChange}
        style={{ display: 'none' }}
      />
    </>
  )

  if (isMobile) {
    return (
      <Layout
        className="clinirag-app-shell clinirag-app-shell--mobile"
        style={{
          height: '100dvh',
          minHeight: '100dvh',
          overflow: 'hidden',
        }}
      >
        <Header className="clinirag-mobile-header">
          <div className="clinirag-header-title">
            <span className="clinirag-header-title__icon">🩺</span>
            <div className="clinirag-header-title__body">
              <Typography.Title
                level={5}
                style={{
                  margin: 0,
                  color: '#1a1a2e',
                  fontWeight: 700,
                  fontSize: 17,
                }}
              >
                临床诊疗问答助手
              </Typography.Title>
            </div>
          </div>

          <Space size={8} align="center" wrap={false}>
            <Button
              size="small"
              icon={<SettingOutlined />}
              onClick={() => {
                setDetailOpen(false)
                setSidebarOpen(true)
              }}
            >
              配置
            </Button>
            <Button
              size="small"
              icon={<AppstoreOutlined />}
              onClick={() => {
                setSidebarOpen(false)
                setDetailOpen(true)
              }}
            >
              详情
            </Button>
            {renderAvatarPicker()}
          </Space>
        </Header>

        <Content className="clinirag-mobile-content">
          <ChatPanel isMobile />
        </Content>

        <Drawer
          className="clinirag-mobile-drawer"
          title="配置中心"
          placement="left"
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          width="86vw"
          styles={{
            body: {
              padding: 0,
              display: 'flex',
              flexDirection: 'column',
              minHeight: 0,
            },
          }}
        >
          <div className="clinirag-mobile-drawer-panel">
            <Sidebar />
          </div>
        </Drawer>

        <Drawer
          className="clinirag-mobile-drawer"
          title="详情面板"
          placement="right"
          open={detailOpen}
          onClose={() => setDetailOpen(false)}
          width="92vw"
          styles={{
            body: {
              padding: 0,
              display: 'flex',
              flexDirection: 'column',
              minHeight: 0,
            },
          }}
        >
          <div className="clinirag-mobile-drawer-panel">
            <DetailPanel />
          </div>
        </Drawer>
      </Layout>
    )
  }

  return (
    <Layout
      className="clinirag-app-shell"
      style={{ height: '100vh', overflow: 'hidden' }}
    >
      <Header
        style={{
          background: '#fff',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 24px',
          height: 56,
          lineHeight: '56px',
          flexShrink: 0,
          boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
        }}
      >
        <Space size={24} align="center">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 20 }}>🩺</span>
            <Typography.Title
              level={4}
              style={{ margin: 0, color: '#1a1a2e', fontWeight: 700 }}
            >
              临床诊疗问答助手
            </Typography.Title>
          </div>
        </Space>
        <Space size={16} align="center">
          {renderAvatarPicker()}
        </Space>
      </Header>

      <Layout style={{ overflow: 'hidden', flex: 1 }}>
        <Sider
          width={240}
          style={{
            background: '#f8f9fc',
            borderRight: '1px solid #eaecf0',
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          <Sidebar />
        </Sider>

        <Content
          style={{
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            background: '#fff',
            minWidth: 0,
          }}
        >
          <ChatPanel />
        </Content>

        <Sider
          width={320}
          style={{
            background: '#fafafa',
            borderLeft: '1px solid #eaecf0',
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          <DetailPanel />
        </Sider>
      </Layout>
    </Layout>
  )
}

async function convertImageToAvatarDataUrl(file: File): Promise<string> {
  const imageDataUrl = await readFileAsDataUrl(file)
  const image = await loadImage(imageDataUrl)
  const canvas = document.createElement('canvas')
  const context = canvas.getContext('2d')

  if (!context) {
    throw new Error('Canvas context unavailable')
  }

  canvas.width = AVATAR_OUTPUT_SIZE
  canvas.height = AVATAR_OUTPUT_SIZE

  const cropSize = Math.min(image.width, image.height)
  const sourceX = (image.width - cropSize) / 2
  const sourceY = (image.height - cropSize) / 2

  context.clearRect(0, 0, canvas.width, canvas.height)
  context.drawImage(
    image,
    sourceX,
    sourceY,
    cropSize,
    cropSize,
    0,
    0,
    canvas.width,
    canvas.height
  )

  return canvas.toDataURL('image/jpeg', 0.9)
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = reject
    image.src = src
  })
}
