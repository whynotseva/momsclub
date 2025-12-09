'use client'

import { memo, ReactNode } from 'react'

type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'info' | 'featured' | 'new' | 'ai'

interface BadgeProps {
  children: ReactNode
  variant?: BadgeVariant
  className?: string
}

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-gray-100 text-gray-700',
  success: 'bg-green-100 text-green-700',
  warning: 'bg-amber-100 text-amber-700',
  error: 'bg-red-100 text-red-700',
  info: 'bg-blue-100 text-blue-700',
  featured: 'bg-gradient-to-r from-amber-400 to-amber-500 text-white shadow-md',
  new: 'bg-green-500 text-white',
  ai: 'bg-gradient-to-r from-purple-500 to-pink-500 text-white',
}

/**
 * Компонент бейджа для статусов
 */
export const Badge = memo(function Badge({
  children,
  variant = 'default',
  className = '',
}: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-1 text-xs font-bold rounded-lg ${variantClasses[variant]} ${className}`}
    >
      {children}
    </span>
  )
})
