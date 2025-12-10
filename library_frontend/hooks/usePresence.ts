'use client'

import { useEffect, useState, useRef, useCallback } from 'react'

interface OnlineUser {
  telegram_id: number
  first_name: string
  username?: string
  photo_url?: string
  admin_group?: string
  connected_at: string
}

interface OnlineUsers {
  library: OnlineUser[]
  admin: OnlineUser[]
}

export interface Activity {
  type: string
  created_at: string
  user: {
    telegram_id: number
    first_name: string
    username?: string
    photo_url?: string
  }
  material: {
    id: number
    title: string
    icon: string
  }
}

export interface AdminAction {
  id: number
  admin_id: number
  admin_name: string
  action: 'create' | 'edit' | 'delete' | 'publish' | 'unpublish'
  entity_type: 'material' | 'category' | 'tag'
  entity_id?: number
  entity_title?: string
  created_at: string
}

interface PresenceData {
  type: string
  data: OnlineUsers | Activity
  library_count?: number
  admin_count?: number
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'wss://api.librarymomsclub.ru'

export function usePresence(
  page: 'library' | 'admin' | null, 
  onNewActivity?: (activity: Activity) => void,
  onAdminAction?: (action: AdminAction) => void
) {
  const [onlineUsers, setOnlineUsers] = useState<OnlineUsers>({ library: [], admin: [] })
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const onNewActivityRef = useRef(onNewActivity)
  const onAdminActionRef = useRef(onAdminAction)
  
  // Обновляем ref при изменении callback
  useEffect(() => {
    onNewActivityRef.current = onNewActivity
  }, [onNewActivity])
  
  useEffect(() => {
    onAdminActionRef.current = onAdminAction
  }, [onAdminAction])

  const connect = useCallback(() => {
    // Не подключаемся если page === null (нет подписки)
    if (!page) return
    
    // Не подключаемся если мы на странице /profile (нет смысла)
    if (typeof window !== 'undefined' && window.location.pathname === '/profile') return
    
    const token = localStorage.getItem('access_token')
    if (!token) return

    // Закрываем старое соединение
    if (wsRef.current) {
      wsRef.current.close()
    }

    try {
      const ws = new WebSocket(`${WS_URL}/ws/presence?token=${token}&page=${page}`)
      wsRef.current = ws

      ws.onopen = () => {
        console.log(`🟢 WebSocket connected (${page})`)
        setIsConnected(true)
        
        // Ping каждые 30 секунд для поддержания соединения
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping')
          }
        }, 30000)
      }

      ws.onmessage = (event) => {
        if (event.data === 'pong') return
        
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'online_users') {
            setOnlineUsers(data.data as OnlineUsers)
          } else if (data.type === 'new_activity' && onNewActivityRef.current) {
            onNewActivityRef.current(data.data as Activity)
          } else if (data.type === 'admin_action' && onAdminActionRef.current) {
            onAdminActionRef.current(data.data as AdminAction)
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }

      ws.onclose = (event) => {
        console.log(`🔴 WebSocket disconnected (${page})`, event.code)
        setIsConnected(false)
        
        // Очищаем ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
        }
        
        // Переподключение через 3 секунды (если не закрыто намеренно)
        if (event.code !== 1000) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('🔄 Reconnecting WebSocket...')
            connect()
          }, 3000)
        }
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
      }
    } catch (e) {
      console.error('Failed to create WebSocket:', e)
    }
  }, [page])

  useEffect(() => {
    // Небольшая задержка для загрузки токена
    const timer = setTimeout(() => {
      connect()
    }, 300)

    return () => {
      clearTimeout(timer)
      
      // Очищаем всё при размонтировании
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted')
      }
    }
  }, [connect])

  return {
    onlineUsers,
    isConnected,
    libraryCount: onlineUsers.library.length,
    adminCount: onlineUsers.admin.length
  }
}
