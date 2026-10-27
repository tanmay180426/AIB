import { motion } from 'framer-motion'

export function HoverCard({ children, className = '' }: { children: React.ReactNode, className?: string }) {
  return (
    <motion.div
      className={className}
      whileHover={{ y: -2 }}
      transition={{ duration: 0.15 }}
      style={{ willChange: 'transform' }}
    >
      {children}
    </motion.div>
  )
}
