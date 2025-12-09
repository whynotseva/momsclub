'use client'

import { memo } from 'react'

interface AvatarProps {
  src?: string | null
  name: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  onClick?: () => void
}

const sizeClasses = {
  sm: 'w-8 h-8 text-xs',
  md: 'w-9 h-9 text-sm',
  lg: 'w-12 h-12 text-base',
  xl: 'w-16 h-16 text-lg',
}

/**
 * Компонент аватара с fallback на инициалы
 */
export const Avatar = memo(function Avatar({
  src,
  name,
  size = 'md',
  className = '',
  onClick,
}: AvatarProps) {
  // Получаем инициалы из имени
  const initials = name
    .split(' ')
    .map(word => word[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  const sizeClass = sizeClasses[size]
  const baseClass = `rounded-full border-2 border-[#E8D4BA] object-cover ${onClick ? 'cursor-pointer hover:border-[#B08968]' : ''} transition-colors`

  if (src) {
    return (
      <img
        src={src}
        alt={name}
        className={`${sizeClass} ${baseClass} ${className}`}
        onClick={onClick}
      />
    )
  }

  // Fallback — инициалы на цветном фоне
  return (
    <div
      className={`${sizeClass} ${baseClass} ${className} flex items-center justify-center bg-gradient-to-br from-[#B08968] to-[#A67C52] text-white font-semibold`}
      onClick={onClick}
    >
      {initials || '?'}
    </div>
  )
})
