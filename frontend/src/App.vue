<script setup>
import Toaster from './components/Toaster.vue'
</script>

<template>
  <RouterView v-slot="{ Component }">
    <Transition name="page-fade" mode="out-in">
      <component :is="Component" />
    </Transition>
  </RouterView>
  <Toaster />
</template>
