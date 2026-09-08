// SPDX-License-Identifier: Apache-2.0
/* Enumerate physical Vulkan identity independently of IREE's filtered indices. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>

static void json_string(const char *s) {
  putchar('"');
  for (const unsigned char *p = (const unsigned char *)s; *p; ++p) {
    if (*p == '"' || *p == '\\') printf("\\%c", *p);
    else if (*p < 32 || *p > 126) printf("\\u%04x", *p);
    else putchar(*p);
  }
  putchar('"');
}

int main(int argc, char **argv) {
  int memory = argc == 2 && strcmp(argv[1], "--memory") == 0;
  if (argc != 1 && !memory) {
    fprintf(stderr, "usage: %s [--memory]\n", argv[0]);
    return 64;
  }
  VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
                           .apiVersion = VK_API_VERSION_1_2};
  VkInstanceCreateInfo create = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
                                 .pApplicationInfo = &app};
  /* Portability implementations (including MoltenVK) are hidden unless the
     instance explicitly opts in. Enable only when advertised by this loader. */
  uint32_t extension_count = 0;
  if (vkEnumerateInstanceExtensionProperties(NULL, &extension_count, NULL) != VK_SUCCESS
      || extension_count > 4096) return 4;
  VkExtensionProperties *extensions = NULL;
  if (extension_count) {
    extensions = calloc(extension_count, sizeof(*extensions));
    if (!extensions) return 4;
    if (vkEnumerateInstanceExtensionProperties(NULL, &extension_count, extensions) != VK_SUCCESS) {
      free(extensions); return 4;
    }
  }
  const char *portability = VK_KHR_PORTABILITY_ENUMERATION_EXTENSION_NAME;
  for (uint32_t i = 0; i < extension_count; ++i) {
    if (strcmp(extensions[i].extensionName, portability) == 0) {
      create.flags |= VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR;
      create.enabledExtensionCount = 1;
      create.ppEnabledExtensionNames = &portability;
      break;
    }
  }
  free(extensions);
  VkInstance instance;
  if (vkCreateInstance(&create, NULL, &instance) != VK_SUCCESS) return 1;
  uint32_t count = 0;
  if (vkEnumeratePhysicalDevices(instance, &count, NULL) != VK_SUCCESS || count > 64) {
    vkDestroyInstance(instance, NULL); return 2;
  }
  VkPhysicalDevice devices[64];
  if (count && vkEnumeratePhysicalDevices(instance, &count, devices) != VK_SUCCESS) {
    vkDestroyInstance(instance, NULL); return 3;
  }
  printf("{\"protocol\":\"%s\",\"devices\":[",
         memory ? "netix-vulkan-memory-v1" : "netix-vulkan-physical-devices-v1");
  for (uint32_t i = 0; i < count; ++i) {
    VkPhysicalDeviceDriverProperties driver = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
    VkPhysicalDeviceIDProperties ids = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES,
                                        .pNext = &driver};
    VkPhysicalDeviceProperties2 properties = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,
                                              .pNext = &ids};
    vkGetPhysicalDeviceProperties2(devices[i], &properties);
    VkPhysicalDeviceProperties p = properties.properties;
    if (i) putchar(',');
    printf("{\"uuid\":\"");
    for (unsigned int j = 0; j < VK_UUID_SIZE; ++j) {
      if (j == 4 || j == 6 || j == 8 || j == 10) putchar('-');
      printf("%02x", ids.deviceUUID[j]);
    }
    printf("\",\"vendor_id\":%u,\"device_id\":%u,\"device_type\":%u,"
           "\"api_version\":%u,\"driver_version\":%u,\"driver_id\":%u,\"name\":",
           p.vendorID, p.deviceID, p.deviceType, p.apiVersion, p.driverVersion, driver.driverID);
    json_string(p.deviceName);
    printf(",\"driver_name\":"); json_string(driver.driverName);
    printf(",\"driver_info\":"); json_string(driver.driverInfo);
    if (memory) {
      VkPhysicalDeviceMemoryProperties heaps;
      vkGetPhysicalDeviceMemoryProperties(devices[i], &heaps);
      printf(",\"memory_topology\":\"%s\",\"heaps\":[",
             p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU ? "shared" : "unknown");
      for (uint32_t h = 0; h < heaps.memoryHeapCount; ++h) {
        if (h) putchar(',');
        printf("{\"index\":%u,\"size_bytes\":%llu,\"device_local\":%s}",
               h, (unsigned long long)heaps.memoryHeaps[h].size,
               (heaps.memoryHeaps[h].flags & VK_MEMORY_HEAP_DEVICE_LOCAL_BIT) ? "true" : "false");
      }
      printf("],\"available_bytes\":null");
    }
    putchar('}');
  }
  puts("]}");
  vkDestroyInstance(instance, NULL);
  return 0;
}
