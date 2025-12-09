'use client'

import { memo, useState } from 'react'

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
 * При ошибке загрузки изображения автоматически показывает инициалы
 */
export const Avatar = memo(function Avatar({
  src,
  name,
  size = 'md',
  className = '',
  onClick,
}: AvatarProps) {
  const [imgError, setImgError] = useState(false)
  
  // Получаем инициалы из имени (защита от null/undefined)
  const initials = (name || '?')
    .split(' ')
    .map(word => word[0] || '')
    .join('')
    .toUpperCase()
    .slice(0, 2) || '?'

  const sizeClass = sizeClasses[size]
  const baseClass = `rounded-full border-2 border-[#E8D4BA] object-cover ${onClick ? 'cursor-pointer hover:border-[#B08968]' : ''} transition-colors`

  // Показываем img только если есть src и нет ошибки загрузки
  if (src && !imgError) {
    return (
      <img
        src={src}
        alt={name}
        className={`${sizeClass} ${baseClass} ${className}`}
        onClick={onClick}
        onError={() => setImgError(true)}
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
