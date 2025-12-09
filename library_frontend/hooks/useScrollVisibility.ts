'use client'

import { useState, useEffect } from 'react'

/**
 * Хук для скрытия/показа элементов при скролле
 * Возвращает isVisible - true когда скроллим вверх или в начале страницы
 */
export function useScrollVisibility() {
  const [isVisible, setIsVisible] = useState(true)
  const [lastScrollY, setLastScrollY] = useState(0)

  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY
      const scrollDiff = currentScrollY - lastScrollY
      
      if (currentScrollY < 50) {
        // В начале страницы — всегда показываем
        setIsVisible(true)
      } else if (scrollDiff > 10) {
        // Скроллим вниз — скрываем
        setIsVisible(false)
      } else if (scrollDiff < -10) {
        // Скроллим вверх — показываем
        setIsVisible(true)
      }
      
      setLastScrollY(currentScrollY)
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [lastScrollY])

  return isVisible
}
