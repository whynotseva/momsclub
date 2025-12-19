'use client'

import { FileText, Plus, Pencil, Trash2, Megaphone, EyeOff } from 'lucide-react'

interface AdminAction {
  id: number
  admin_id: number
  admin_name: string
  action: 'create' | 'edit' | 'delete' | 'publish' | 'unpublish'
  entity_type: 'material' | 'category' | 'tag'
  entity_id?: number
  entity_title?: string
  details?: string
  created_at: string
}

interface HistoryTabProps {
  adminHistory: AdminAction[]
  loadingHistory: boolean
}

/**
 * Таб истории действий админов
 */
export function HistoryTab({ adminHistory, loadingHistory }: HistoryTabProps) {
  return (
    <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-lg rounded-2xl border border-[#E8D4BA]/30 dark:border-[#3D3D3D] overflow-hidden">
      <div className="p-4 border-b border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
        <h2 className="text-lg font-bold text-[#5D4E3A] dark:text-[#E5E5E5] flex items-center gap-2"><FileText className="w-5 h-5 text-[#B08968]" /> История действий</h2>
        <p className="text-sm text-[#8B8279] dark:text-[#707070]">Все действия админов в библиотеке</p>
      </div>
      
      {loadingHistory ? (
        <div className="p-8 text-center text-[#8B8279] dark:text-[#707070]">Загрузка...</div>
      ) : adminHistory.length === 0 ? (
        <div className="p-8 text-center text-[#8B8279] dark:text-[#707070]">История пуста</div>
      ) : (
        <div className="divide-y divide-[#E8D4BA]/30 dark:divide-[#3D3D3D] max-h-[600px] overflow-y-auto">
          {adminHistory.map((action) => {
            const actionConfig = {
              create: { icon: Plus, color: 'text-green-600 dark:text-green-400', bg: 'bg-green-50 dark:bg-green-900/30', label: 'создал(а)' },
              edit: { icon: Pencil, color: 'text-yellow-600 dark:text-yellow-400', bg: 'bg-yellow-50 dark:bg-yellow-900/30', label: 'изменил(а)' },
              delete: { icon: Trash2, color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 dark:bg-red-900/30', label: 'удалил(а)' },
              publish: { icon: Megaphone, color: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-50 dark:bg-blue-900/30', label: 'опубликовал(а)' },
              unpublish: { icon: EyeOff, color: 'text-gray-600 dark:text-gray-400', bg: 'bg-gray-50 dark:bg-gray-800/50', label: 'снял(а) с публикации' }
            }[action.action] || { icon: FileText, color: 'text-gray-600 dark:text-gray-400', bg: 'bg-gray-50 dark:bg-gray-800/50', label: action.action }
            
            const entityLabel = {
              material: 'материал',
              category: 'категорию',
              tag: 'тег'
            }[action.entity_type] || action.entity_type
            
            return (
              <div key={action.id} className={`p-4 flex items-start gap-3 ${actionConfig.bg}`}>
                <actionConfig.icon className={`w-5 h-5 ${actionConfig.color}`} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-[#5D4E3A] dark:text-[#E5E5E5]">
                    <span className="font-medium">{action.admin_name}</span>
                    {' '}
                    <span className={actionConfig.color}>{actionConfig.label}</span>
                    {' '}
                    {entityLabel}
                    {action.entity_title && (
                      <span className="font-medium"> «{action.entity_title}»</span>
                    )}
                  </p>
                  <p className="text-xs text-[#8B8279] dark:text-[#707070] mt-1">
                    {new Date(action.created_at).toLocaleString('ru-RU', {
                      day: 'numeric',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit'
                    })}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
