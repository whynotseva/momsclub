'use client'

import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { api } from '@/lib/api'

interface Tariff {
  id: string
  name: string
  price: number
  priceFirst?: number
  days: number
  popular?: boolean
}

const TARIFFS: Tariff[] = [
  { id: '1month', name: '1 месяц', price: 990, priceFirst: 690, days: 30, popular: true },
  { id: '2months', name: '2 месяца', price: 1790, days: 60 },
  { id: '3months', name: '3 месяца', price: 2490, days: 90 },
]

interface PaymentModalProps {
  isOpen: boolean
  onClose: () => void
  isFirstPayment?: boolean
  hasSubscription?: boolean
}

export default function PaymentModal({ isOpen, onClose, isFirstPayment = false, hasSubscription = false }: PaymentModalProps) {
  const [selectedTariff, setSelectedTariff] = useState<string>('1month')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Блокировка скролла
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [isOpen])

  const handlePayment = async () => {
    setLoading(true)
    setError(null)
    
    try {
      const response = await api.post('/auth/create-payment', {
        tariff: selectedTariff
      })
      
      // Редирект на страницу оплаты ЮКассы
      if (response.data.payment_url) {
        window.location.href = response.data.payment_url
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      setError(error.response?.data?.detail || 'Ошибка создания платежа')
    } finally {
      setLoading(false)
    }
  }

  const getPrice = (tariff: Tariff) => {
    if (isFirstPayment && tariff.priceFirst && tariff.id === '1month') {
      return tariff.priceFirst
    }
    return tariff.price
  }

  const getSavings = (tariff: Tariff) => {
    const pricePerMonth = tariff.price / (tariff.days / 30)
    const basePrice = 990
    if (pricePerMonth < basePrice) {
      return Math.round((1 - pricePerMonth / basePrice) * 100)
    }
    return 0
  }

  if (!isOpen) return null

  return createPortal(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4" style={{ zIndex: 9999 }}>
      <div className="bg-white rounded-2xl p-6 max-w-md w-full shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-[#2D2A26]">
            {hasSubscription ? '🔄 Продлить подписку' : '✨ Оформить подписку'}
          </h2>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* First payment badge */}
        {isFirstPayment && (
          <div className="mb-4 p-3 bg-gradient-to-r from-green-50 to-emerald-50 rounded-xl border border-green-200/50">
            <div className="flex items-center gap-2">
              <span className="text-lg">🎁</span>
              <div>
                <p className="text-sm font-medium text-green-700">Первая оплата со скидкой!</p>
                <p className="text-xs text-green-600">1 месяц всего за 690₽ вместо 990₽</p>
              </div>
            </div>
          </div>
        )}

        {/* Tariffs */}
        <div className="space-y-3 mb-6">
          {TARIFFS.map((tariff) => {
            const price = getPrice(tariff)
            const savings = getSavings(tariff)
            const isSelected = selectedTariff === tariff.id
            const showFirstDiscount = isFirstPayment && tariff.priceFirst && tariff.id === '1month'
            
            return (
              <button
                key={tariff.id}
                onClick={() => setSelectedTariff(tariff.id)}
                className={`w-full p-4 rounded-xl border-2 transition-all text-left relative ${
                  isSelected
                    ? 'border-[#B08968] bg-[#FAF6F1]'
                    : 'border-[#E8D4BA]/50 hover:border-[#B08968]/50'
                }`}
              >
                {tariff.popular && (
                  <span className="absolute -top-2 right-3 px-2 py-0.5 bg-gradient-to-r from-[#B08968] to-[#C9A882] text-white text-xs rounded-full">
                    Популярный
                  </span>
                )}
                
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-semibold text-[#2D2A26]">{tariff.name}</p>
                    <p className="text-xs text-[#8B8279]">{tariff.days} дней доступа</p>
                  </div>
                  
                  <div className="text-right">
                    <div className="flex items-center gap-2">
                      {showFirstDiscount && (
                        <span className="text-sm text-[#8B8279] line-through">{tariff.price}₽</span>
                      )}
                      <span className="text-lg font-bold text-[#2D2A26]">{price}₽</span>
                    </div>
                    {savings > 0 && !showFirstDiscount && (
                      <span className="text-xs text-green-600">Экономия {savings}%</span>
                    )}
                    {showFirstDiscount && (
                      <span className="text-xs text-green-600">-30%</span>
                    )}
                  </div>
                </div>
                
                {/* Selection indicator */}
                <div className={`absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                  isSelected ? 'border-[#B08968] bg-[#B08968]' : 'border-[#E8D4BA]'
                }`}>
                  {isSelected && <span className="text-white text-xs">✓</span>}
                </div>
              </button>
            )
          })}
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-3 bg-red-50 rounded-xl border border-red-200 text-sm text-red-600">
            {error}
          </div>
        )}

        {/* Submit button */}
        <button
          onClick={handlePayment}
          disabled={loading}
          className="w-full py-3 bg-gradient-to-r from-[#B08968] via-[#A67C52] to-[#96704A] text-white font-semibold rounded-xl shadow-lg shadow-[#B08968]/25 hover:shadow-xl hover:-translate-y-0.5 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Создание платежа...
            </span>
          ) : (
            `Оплатить ${getPrice(TARIFFS.find(t => t.id === selectedTariff)!)}₽`
          )}
        </button>

        {/* Payment info */}
        <div className="mt-4 text-center">
          <p className="text-xs text-[#8B8279]">
            💳 Безопасная оплата через ЮКассу
          </p>
          <p className="text-xs text-[#8B8279] mt-1">
            После оплаты подписка активируется автоматически
          </p>
        </div>
      </div>
    </div>,
    document.body
  )
}
