'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api'

interface UserSettings {
  birthday?: string
  is_recurring_active: boolean
  has_saved_card?: boolean
}

export function SettingsCard() {
  const [settings, setSettings] = useState<UserSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [birthdayInput, setBirthdayInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [showCancelModal, setShowCancelModal] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [enabling, setEnabling] = useState(false)

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const response = await api.get('/auth/settings')
        setSettings(response.data)
        if (response.data.birthday) {
          setBirthdayInput(response.data.birthday)
        }
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error'
        console.error('[SettingsCard] Error:', err)
        setError(errorMessage)
      } finally {
        setLoading(false)
      }
    }
    loadSettings()
  }, [])

  const saveBirthday = async () => {
    setSaving(true)
    try {
      const response = await api.put('/auth/settings', { birthday: birthdayInput || null })
      setSettings(response.data)
      setIsEditing(false)
    } catch (err) {
      console.error('[SettingsCard] Save error:', err)
      alert('Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const cancelReasons = [
    { id: 'expensive', label: '💸 Дорого' },
    { id: 'no_use', label: '📉 Не использую контент' },
    { id: 'pause', label: '⏸ Временная пауза' },
    { id: 'expectations', label: '😞 Не оправдал ожидания' },
    { id: 'technical', label: '🔄 Технические проблемы' },
  ]

  const submitCancelRequest = async () => {
    if (!cancelReason) {
      alert('Выберите причину')
      return
    }
    setCancelling(true)
    try {
      await api.post('/auth/cancel-autorenewal', { reason: cancelReason })
      alert('✅ Заявка на отмену автопродления создана! Админ рассмотрит её в ближайшее время.')
      setShowCancelModal(false)
      setCancelReason('')
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      alert(error.response?.data?.detail || 'Ошибка создания заявки')
    } finally {
      setCancelling(false)
    }
  }

  const enableAutorenewal = async () => {
    setEnabling(true)
    try {
      await api.post('/auth/enable-autorenewal')
      // Обновляем настройки
      const response = await api.get('/auth/settings')
      setSettings(response.data)
      alert('✅ Автопродление включено!')
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      alert(error.response?.data?.detail || 'Ошибка включения автопродления')
    } finally {
      setEnabling(false)
    }
  }

  const formatBirthday = (dateStr?: string) => {
    if (!dateStr) return null
    try {
      const date = new Date(dateStr)
      return date.toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long'
      })
    } catch {
      return dateStr
    }
  }

  if (loading) {
    return (
      <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6">
        <div className="animate-pulse space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#E8D4BA]/50 rounded-xl" />
            <div className="h-5 bg-[#E8D4BA]/50 rounded w-24" />
          </div>
          <div className="space-y-2">
            <div className="h-10 bg-[#E8D4BA]/30 rounded-xl" />
            <div className="h-10 bg-[#E8D4BA]/30 rounded-xl" />
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-xl">⚙️</span>
          <h2 className="text-lg font-semibold text-[#2D2A26]">Настройки</h2>
        </div>
        <p className="text-sm text-[#8B8279]">Не удалось загрузить данные</p>
      </div>
    )
  }

  return (
    <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6 hover:shadow-xl transition-shadow">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 bg-gradient-to-br from-[#B08968] to-[#C9A882] rounded-xl flex items-center justify-center">
          <span className="text-white text-lg">⚙️</span>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-[#2D2A26]">Настройки</h2>
          <p className="text-sm text-[#8B8279]">Управление аккаунтом</p>
        </div>
      </div>

      {/* Settings List */}
      <div className="space-y-3">
        {/* Birthday */}
        <div className="p-3 bg-[#FAF6F1] rounded-xl">
          {isEditing ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="text-xl">🎂</span>
                <p className="font-medium text-[#2D2A26]">День рождения</p>
              </div>
              <input
                type="date"
                value={birthdayInput}
                onChange={(e) => setBirthdayInput(e.target.value)}
                className="w-full px-3 py-2 border border-[#E8D4BA] rounded-lg text-[#2D2A26] focus:outline-none focus:ring-2 focus:ring-[#B08968]"
              />
              <div className="flex gap-2">
                <button
                  onClick={saveBirthday}
                  disabled={saving}
                  className="flex-1 py-2 bg-[#B08968] text-white rounded-lg hover:bg-[#8B7355] transition-colors disabled:opacity-50"
                >
                  {saving ? 'Сохранение...' : 'Сохранить'}
                </button>
                <button
                  onClick={() => {
                    setIsEditing(false)
                    setBirthdayInput(settings?.birthday || '')
                  }}
                  className="px-4 py-2 border border-[#E8D4BA] text-[#8B8279] rounded-lg hover:bg-[#FAF6F1] transition-colors"
                >
                  Отмена
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-xl">🎂</span>
                <div>
                  <p className="font-medium text-[#2D2A26]">День рождения</p>
                  <p className="text-xs text-[#8B8279]">
                    {settings?.birthday 
                      ? formatBirthday(settings.birthday)
                      : 'Не указан'}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setIsEditing(true)}
                className="px-3 py-1 text-xs text-[#B08968] border border-[#B08968] rounded-lg hover:bg-[#B08968] hover:text-white transition-colors"
              >
                {settings?.birthday ? 'Изменить' : 'Указать'}
              </button>
            </div>
          )}
        </div>

        {/* Auto-renewal */}
        <div className="p-3 bg-[#FAF6F1] rounded-xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-xl">🔄</span>
              <div>
                <p className="font-medium text-[#2D2A26]">Автопродление</p>
                <p className="text-xs text-[#8B8279]">
                  {settings?.is_recurring_active 
                    ? 'Подписка продлится автоматически'
                    : 'Выключено'}
                </p>
              </div>
            </div>
            {settings?.is_recurring_active ? (
              <button
                onClick={() => setShowCancelModal(true)}
                className="px-3 py-1 text-xs text-red-600 border border-red-300 rounded-lg hover:bg-red-50 transition-colors"
              >
                Отключить
              </button>
            ) : settings?.has_saved_card ? (
              <button
                onClick={enableAutorenewal}
                disabled={enabling}
                className="px-3 py-1 text-xs text-green-600 border border-green-300 rounded-lg hover:bg-green-50 transition-colors disabled:opacity-50"
              >
                {enabling ? '...' : 'Включить'}
              </button>
            ) : (
              <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">
                Выкл
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Cancel Modal */}
      {showCancelModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4" style={{ zIndex: 9999 }}>
          <div className="bg-white rounded-2xl p-6 max-w-sm w-full shadow-2xl">
            <h3 className="text-lg font-semibold text-[#2D2A26] mb-2">
              Отключить автопродление?
            </h3>
            <p className="text-sm text-[#8B8279] mb-4">
              Выберите причину, это поможет нам стать лучше
            </p>
            
            <div className="space-y-2 mb-4">
              {cancelReasons.map((reason) => (
                <button
                  key={reason.id}
                  onClick={() => setCancelReason(reason.label)}
                  className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                    cancelReason === reason.label
                      ? 'border-[#B08968] bg-[#FAF6F1]'
                      : 'border-[#E8D4BA] hover:bg-[#FAF6F1]'
                  }`}
                >
                  {reason.label}
                </button>
              ))}
            </div>

            <div className="flex gap-2">
              <button
                onClick={submitCancelRequest}
                disabled={cancelling || !cancelReason}
                className="flex-1 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors disabled:opacity-50"
              >
                {cancelling ? 'Отправка...' : 'Отправить заявку'}
              </button>
              <button
                onClick={() => {
                  setShowCancelModal(false)
                  setCancelReason('')
                }}
                className="px-4 py-2 border border-[#E8D4BA] text-[#8B8279] rounded-lg hover:bg-[#FAF6F1] transition-colors"
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
