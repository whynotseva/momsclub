'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api'

interface ReferralInfo {
  referral_code: string
  referral_link: string
  referral_balance: number
  total_referrals: number
  paid_referrals: number
  total_earned: number
  bonus_percent: number
  bonus_days: number
}

export function ReferralCard() {
  const [referral, setReferral] = useState<ReferralInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const loadReferral = async () => {
      try {
        console.log('[ReferralCard] Loading referral data...')
        const response = await api.get('/auth/referral')
        console.log('[ReferralCard] Data loaded:', response.data)
        setReferral(response.data)
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error'
        console.error('[ReferralCard] Error loading referral:', err)
        setError(errorMessage)
      } finally {
        setLoading(false)
      }
    }
    loadReferral()
  }, [])

  const copyLink = async () => {
    if (!referral) return
    try {
      await navigator.clipboard.writeText(referral.referral_link)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  const formatMoney = (kopecks: number) => {
    return (kopecks / 100).toLocaleString('ru-RU') + ' ₽'
  }

  if (loading) {
    return (
      <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6">
        <div className="animate-pulse space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#E8D4BA]/50 rounded-xl" />
            <div className="h-5 bg-[#E8D4BA]/50 rounded w-32" />
          </div>
          <div className="h-12 bg-[#E8D4BA]/30 rounded-xl" />
          <div className="grid grid-cols-2 gap-3">
            <div className="h-16 bg-[#E8D4BA]/30 rounded-xl" />
            <div className="h-16 bg-[#E8D4BA]/30 rounded-xl" />
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-xl">👥</span>
          <h2 className="text-lg font-semibold text-[#2D2A26]">Реферальная программа</h2>
        </div>
        <p className="text-sm text-[#8B8279]">Не удалось загрузить данные</p>
      </div>
    )
  }

  if (!referral) return null

  return (
    <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6 hover:shadow-xl transition-shadow">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 bg-gradient-to-br from-[#B08968] to-[#C9A882] rounded-xl flex items-center justify-center">
          <span className="text-white text-lg">👥</span>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-[#2D2A26]">Реферальная программа</h2>
          <p className="text-xs text-[#8B8279]">Приглашай друзей — получай бонусы</p>
        </div>
      </div>

      {/* Referral Link */}
      <div className="mb-4">
        <label className="text-xs text-[#8B8279] mb-1.5 block">Твоя ссылка для приглашения</label>
        <div className="flex gap-2">
          <div className="flex-1 bg-[#F5EFE6] rounded-xl px-3 py-2.5 text-sm text-[#5D4E3A] truncate font-mono">
            {referral.referral_link}
          </div>
          <button
            onClick={copyLink}
            className={`px-4 py-2.5 rounded-xl font-medium text-sm transition-all ${
              copied
                ? 'bg-green-500 text-white'
                : 'bg-gradient-to-r from-[#B08968] to-[#C9A882] text-white hover:shadow-lg'
            }`}
          >
            {copied ? '✓' : 'Копировать'}
          </button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-[#F5EFE6]/50 rounded-xl p-3 text-center">
          <div className="text-2xl font-bold text-[#B08968]">{referral.total_referrals}</div>
          <div className="text-xs text-[#8B8279]">Приглашено</div>
        </div>
        <div className="bg-[#F5EFE6]/50 rounded-xl p-3 text-center">
          <div className="text-2xl font-bold text-[#B08968]">{referral.paid_referrals}</div>
          <div className="text-xs text-[#8B8279]">Оплатили</div>
        </div>
      </div>

      {/* Balance */}
      {referral.referral_balance > 0 && (
        <div className="bg-gradient-to-r from-[#B08968]/10 to-[#C9A882]/10 rounded-xl p-4 mb-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs text-[#8B8279]">Баланс</div>
              <div className="text-xl font-bold text-[#B08968]">{formatMoney(referral.referral_balance)}</div>
            </div>
            <button className="px-4 py-2 bg-white rounded-xl text-sm font-medium text-[#B08968] border border-[#E8D4BA] hover:bg-[#F5EFE6] transition-colors">
              Вывести
            </button>
          </div>
          {referral.total_earned > 0 && (
            <div className="text-xs text-[#8B8279] mt-2">
              Всего заработано: {formatMoney(referral.total_earned)}
            </div>
          )}
        </div>
      )}

      {/* Bonus Info */}
      <div className="bg-[#F5EFE6]/30 rounded-xl p-3">
        <div className="text-xs text-[#8B8279] mb-2">Твои бонусы за реферала:</div>
        <div className="flex gap-4">
          <div className="flex items-center gap-1.5">
            <span className="text-base">💰</span>
            <span className="text-sm font-medium text-[#5D4E3A]">{referral.bonus_percent}% от оплаты</span>
          </div>
          <div className="text-[#E8D4BA]">или</div>
          <div className="flex items-center gap-1.5">
            <span className="text-base">📅</span>
            <span className="text-sm font-medium text-[#5D4E3A]">+{referral.bonus_days} дней</span>
          </div>
        </div>
      </div>
    </div>
  )
}
